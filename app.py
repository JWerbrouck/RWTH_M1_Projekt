from __future__ import print_function
import csv
import os
import sys
import time
import operator
import functools
import OCC.AIS
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from collections import defaultdict, Iterable, OrderedDict

#import for extra propertyfunctionality
import uuid
import ifcopenshell
import rdflib
import rdflib.plugins.sparql
from rdflib import *
from rdflib import resource
from ifcopenshell import ifcopenshell_wrapper

import sys
reload(sys)
sys.setdefaultencoding('utf-8')

os.environ['QT_API'] = 'pyqt4'
try:
    from pyqode.qt import QtCore
except: pass

from PyQt4 import QtGui, QtCore

from code_editor_pane import code_edit

try: from OCC.Display.pyqt4Display import qtViewer3d
except:
    import OCC.Display

    try: import OCC.Display.backend
    except: pass

    try: OCC.Display.backend.get_backend("qt-pyqt4")
    except: OCC.Display.backend.load_backend("qt-pyqt4")

    from OCC.Display.qtDisplay import qtViewer3d

from main import settings, iterator
from occ_utils import display_shape

from ifcopenshell import open as open_ifc_file
from ifcopenshell import get_supertype

# Depending on Python version and what not there may or may not be a QString
try:
    from PyQt4.QtCore import QString
except ImportError:
    QString = str

class snippet_save_dialogue(QtGui.QDialog):
    pass

class configuration(object):
    def __init__(self):
        try:
            import ConfigParser
            Cfg = ConfigParser.RawConfigParser
        except:
            import configparser
            Cfg = configparser.ConfigParser(interpolation=None)

        self.conf_file = os.path.expanduser(os.path.join("~", ".ifcopenshell", "app", "snippets.conf"))
        if self.conf_file.startswith("~"):
            conf_file = None
            return

        self.config_encode = lambda s: s.replace("\\", "\\\\").replace("\n", "\n|")
        self.config_decode = lambda s: s.replace("\n|", "\n").replace("\\\\", "\\")

        if not os.path.exists(os.path.dirname(self.conf_file)):
            os.makedirs(os.path.dirname(self.conf_file))

        if not os.path.exists(self.conf_file):
            self.config = Cfg()
            self.config.add_section("snippets")
            self.config.set("snippets", "print all wall ids", self.config_encode("""
###########################################################################
# A simple script that iterates over all walls in the current model       #
# and prints their Globally unique IDs (GUIDS) to the console window      #
###########################################################################

for wall in model.by_type("IfcWall"):
    print ("wall with global id: "+str(wall.GlobalId))
""".lstrip()))

            self.config.set("snippets", "print properties of current selection", self.config_encode("""
###########################################################################
# A simple script that iterates over all IfcPropertySets of the currently #
# selected object and prints them to the console                          #
###########################################################################
""".lstrip()))
        self.config = Cfg()
        self.config.read(self.conf_file)

    def save_configuration(self):

        with open(self.conf_file, 'w') as configfile:
            self.config.write(configfile)

    def set_snippets(self,snippets):
        pass

    def options(self, s):
        return OrderedDict([(k, self.config_decode(self.config.get(s, k))) for k in self.config.options(s)])

class application(QtGui.QApplication):

    """A pythonOCC, PyQt based IfcOpenShell application
    with two tree views and a graphical 3d view"""

    class abstract_treeview(QtGui.QTreeWidget):

        """Base class for the two treeview controls"""

        instanceSelected = QtCore.pyqtSignal([object])
        instanceVisibilityChanged = QtCore.pyqtSignal([object, int])
        instanceDisplayModeChanged = QtCore.pyqtSignal([object, int])

        def __init__(self):
            QtGui.QTreeView.__init__(self)
            self.setColumnCount(len(self.ATTRIBUTES))
            self.setHeaderLabels(self.ATTRIBUTES)
            self.children = defaultdict(list)

        def get_children(self, inst):
            c = [inst]
            i = 0
            while i < len(c):
                c.extend(self.children[c[i]])
                i += 1
            return c

        def contextMenuEvent(self, event):
            menu = QtGui.QMenu(self)
            visibility = [menu.addAction("Show"), menu.addAction("Hide")]
            displaymode = [menu.addAction("Solid"), menu.addAction("Wireframe")]
            action = menu.exec_(self.mapToGlobal(event.pos()))
            index = self.selectionModel().currentIndex()
            inst = index.data(QtCore.Qt.UserRole)
            if hasattr(inst, 'toPyObject'):
                inst = inst.toPyObject()
            if action in visibility:
                self.instanceVisibilityChanged.emit(inst, visibility.index(action))
            elif action in displaymode:
                self.instanceDisplayModeChanged.emit(inst, displaymode.index(action))

        def clicked(self, index):
            inst = index.data(QtCore.Qt.UserRole)
            if hasattr(inst, 'toPyObject'):
                inst = inst.toPyObject()
            if inst:
                self.instanceSelected.emit(inst)

        def select(self, product):
            itm = self.product_to_item.get(product)
            if itm is None: return
            self.selectionModel().setCurrentIndex(itm, QtGui.QItemSelectionModel.SelectCurrent | QtGui.QItemSelectionModel.Rows);

    class decomposition_treeview(abstract_treeview):

        """Treeview with typical IFC decomposition relationships"""

        ATTRIBUTES = ['Entity', 'GlobalId', 'Name']

        def parent(self, instance):
            if instance.is_a("IfcOpeningElement"):
                return instance.VoidsElements[0].RelatingBuildingElement
            if instance.is_a("IfcElement"):
                fills = instance.FillsVoids
                if len(fills):
                    return fills[0].RelatingOpeningElement
                containments = instance.ContainedInStructure
                if len(containments):
                    return containments[0].RelatingStructure
            if instance.is_a("IfcObjectDefinition"):
                decompositions = instance.Decomposes
                if len(decompositions):
                    return decompositions[0].RelatingObject

        def load_file(self, f, **kwargs):
            products = list(f.by_type("IfcProduct")) + list(f.by_type("IfcProject"))
            parents = list(map(self.parent, products))
            items = {}
            skipped = 0
            ATTRS = self.ATTRIBUTES
            while len(items) + skipped < len(products):
                for product, parent in zip(products, parents):
                    if parent is None and not product.is_a("IfcProject"):
                        skipped += 1
                        continue
                    if (parent is None or parent in items) and product not in items:
                        sl = []
                        for attr in ATTRS:
                            if attr == 'Entity':
                                sl.append(product.is_a())
                            else:
                                sl.append(getattr(product, attr) or '')
                        itm = items[product] = QtGui.QTreeWidgetItem(items.get(parent, self), sl)
                        itm.setData(0, QtCore.Qt.UserRole, product)
                        self.children[parent].append(product)
            self.product_to_item = dict(zip(items.keys(), map(self.indexFromItem, items.values())))
            self.connect(self, QtCore.SIGNAL("clicked(const QModelIndex &)"), self.clicked)
            self.expandAll()

    class type_treeview(abstract_treeview):

        """Treeview with typical IFC decomposition relationships"""

        ATTRIBUTES = ['Name']

        def load_file(self, f, **kwargs):
            products = list(f.by_type("IfcProduct"))
            types = set(map(lambda i: i.is_a(), products))
            items = {}
            for t in types:
                def add(t):
                    s = get_supertype(t)
                    if s: add(s)
                    s2, t2 = map(QString, (s,t))
                    if t2 not in items:
                        itm = items[t2] = QtGui.QTreeWidgetItem(items.get(s2, self), [t2])
                        itm.setData(0, QtCore.Qt.UserRole, t2)
                        self.children[s2].append(t2)
                add(t)

            for p in products:
                t = QString(p.is_a())
                itm = items[p] = QtGui.QTreeWidgetItem(items.get(t, self), [p.Name or '<no name>'])
                itm.setData(0, QtCore.Qt.UserRole, t)
                self.children[t].append(p)

            self.product_to_item = dict(zip(items.keys(), map(self.indexFromItem, items.values())))
            self.connect(self, QtCore.SIGNAL("clicked(const QModelIndex &)"), self.clicked)
            self.expandAll()

    #definition of 'collecting' lists
    global MatchingList
    MatchingList=[]
    global FinalSPARQLquery
    FinalSPARQLquery=[]
    global FolderList
    FolderList=['FirstItem']
    global subjectList_model
    subjectList_model=[]
    global predicateList_model
    predicateList_model=[]
    global objectList_model
    objectList_model=[]
    global prod_pname_text
    prod_pname_text=[[None,None,None]]

    class property_table(QtGui.QWidget):

        def __init__(self):
            QtGui.QWidget.__init__(self)
            self.layout= QtGui.QVBoxLayout(self)
            self.setLayout(self.layout)
            self.scroll = QtGui.QScrollArea(self)
            self.layout.addWidget(self.scroll)
            self.scroll.setWidgetResizable(True)
            self.scrollContent = QtGui.QWidget(self.scroll)
            self.scrollLayout = QtGui.QVBoxLayout(self.scrollContent)
            self.scrollContent.setLayout(self.scrollLayout)
            self.scroll.setWidget(self.scrollContent)
            self.prop_dict = {}

        global finalcproplist
        finalcproplist=[]
        global definitiveproplist
        definitiveproplist=[]
        global datasetList
        datasetList=['']
        global selected_referencelist
        selected_referencelist=[]
        global textlist
        textlist=[]
        global changelist
        changelist=[]

        global cpropsetsviewer
        def cpropsetsviewer(self):
            info_dialog=QDialog()
            info_dialog.setWindowTitle('Overview of custom propertysets')
            overall_layout=QVBoxLayout()
            info_dialog.setLayout(overall_layout)

            for item in finalcproplist:
                for prod,cpset in item.iteritems():
                    productbox=QtGui.QGroupBox()
                    productbox.setTitle(prod.Name)
                    cpropgroup_layout=QVBoxLayout()
                    for cpset_title,cprops in cpset.iteritems():
                        title=QLabel('Propertyset:'+str(cpset_title))
                        cpropgroup_layout.addWidget(title)
                        for propitem in cprops:
                            singleproperty=QLabel('\t'+str(propitem))
                            cpropgroup_layout.addWidget(singleproperty)

                    productbox.setLayout(cpropgroup_layout)
                    overall_layout.addWidget(productbox)



            info_dialog.show()
            sys.exit(app.exec_())

        #this definition collects the changes stored in the different lists and writes them to an external .ifc-file
        global save_to_file
        def save_to_file(self):
            print('finalcproplist is: custom propsets')
            print(finalcproplist)
            print('definitiveproplist is: changed values')
            print(definitiveproplist)

            fileName = QtGui.QFileDialog.getSaveFileName(None, 'Choose save directory', '', "Industry Foundation Classes (*.ifc)")

            if fileName:
                print('saving properties to: '+fileName)
                fileName_string=str(fileName)


            forbidden_psetlist=[]
            allowed_psetlist=[]

            for entity in f:
                if entity.is_a("IfcPropertySet"):
                    forbidden_psetlist.append(str(entity.Name))

            for item in finalcproplist:
                for prod,cpset in item.iteritems():
                    for cpset_title,cprops in cpset.iteritems():
                        if str(cpset_title) not in forbidden_psetlist:
                            allowed_psetlist.append(item)

            for item in allowed_psetlist:
                for prod,cpset in item.iteritems():
                    product=prod
                    for cpset_title,cprops in cpset.iteritems():
                        prop_set_guid = ifcopenshell.guid.compress(uuid.uuid1().hex)
                        property_values = []
                        for propitem in cprops:
                            writename=str(propitem[0])
                            writedescription=str(propitem[1])
                            writenominalvalue=str(propitem[2])
                            writewrappedvalue=str(propitem[3])
                            writeunit=str(propitem[4])
                            try: writeproperty=f.createIfcPropertySingleValue(writename,writedescription, f.create_entity(writenominalvalue, writewrappedvalue), None)
                            except:
                                try: writeproperty=f.createIfcPropertySingleValue(writename,writedescription, f.create_entity(writenominalvalue, float(writewrappedvalue)), None)
                                except:
                                    try: writeproperty=f.createIfcPropertySingleValue(writename,writedescription, f.create_entity(writenominalvalue, int(writewrappedvalue)), None)
                                    except:
                                        try: writeproperty=f.createIfcPropertySingleValue(writename,writedescription, f.create_entity(writenominalvalue, bool(writewrappedvalue)), None)
                                        except:
                                            print("Property could not be written to file. Please check if all values are correct")

                            property_values.append(writeproperty)

                        property_set = f.createIfcPropertySet(prop_set_guid, product.OwnerHistory, cpset_title, None, property_values)
                        rel_guid = ifcopenshell.guid.compress(uuid.uuid1().hex)
                        f.createIfcRelDefinesByProperties(rel_guid, product.OwnerHistory, None, None, [product], property_set)

            for bounded_item in definitiveproplist:
                for product, changelist in bounded_item.iteritems():
                    for item in changelist:
                        for prop_name,new_value in item.iteritems():
                            for i in range(len(product.IsDefinedBy)):
                                if list(product.IsDefinedBy)[i].is_a("IfcRelDefinesByProperties"):
                                    relDefinesByProperties=list(product.IsDefinedBy)[i]
                                    #make a distinction between IfcPropertySet and IfcElementQuantity
                                    if relDefinesByProperties.RelatingPropertyDefinition.is_a("IfcPropertySet"):
                                        for prop in relDefinesByProperties.RelatingPropertyDefinition.HasProperties:
                                            #try the possible types for each value (str, float,bool, int)
                                            if prop.Name==prop_name:
                                                try: prop.NominalValue.wrappedValue = new_value
                                                except:
                                                    try: prop.NominalValue.wrappedValue = float(new_value)
                                                    except:
                                                        try: prop.NominalValue.wrappedValue = bool(new_value)
                                                        except:
                                                            try: prop.NominalValue.wrappedValue = int(new_value)
                                                            except: pass

                                    elif relDefinesByProperties.RelatingPropertyDefinition.is_a("IfcElementQuantity"):
                                        for prop in relDefinesByProperties.RelatingPropertyDefinition.Quantities:
                                            if prop.Name==prop_name:
                                                try: prop.LengthValue = new_value
                                                except:
                                                    try: prop.LengthValue = float(new_value)
                                                    except:
                                                        try: prop.LengthValue = int(new_value)
                                                        except:
                                                            try: prop.LengthValue = bool(new_value)
                                                            except: pass

            forbiddenreference=[]
            allowedreference=[]
            for entity in f:
                if entity.is_a("IfcExternalReference"):
                    forbiddenreference.append(str(entity.Location))

            for item in selected_referencelist:
                URI=str(item[0][0])
                if URI not in forbiddenreference:
                    allowedreference.append(item)

            for couple in allowedreference:
                referencedURI=couple[0][0]
                referencedProduct=couple[1]
                f.createIfcExternalReference(str(referencedURI),None,None)
                #IFCEXTERNALREFERENCERELATIONSHIP not implemented in IfcOpenShell
                '''for entity in f:
                    if entity.is_a("IfcExternalReference"):
                        print(tuple(entity))
                        if str(tuple(entity)[0])==str(referencedURI):
                            print("ok")
                            f.createIfcExternalReferenceRelationship(None,None,entity,referencedProduct)'''

            f.write(fileName_string)
            win.close()

        #triggered by selection event in either component of parent
        def select(self, product):
            # Clear the old contents if any
            while self.scrollLayout.count():
                child = self.scrollLayout.takeAt(0)
                if child is not None:
                    if child.widget() is not None:
                        child.widget().deleteLater()

            self.scroll = QtGui.QScrollArea()
            self.scroll.setWidgetResizable(True)
            prop_sets = self.prop_dict.get(str(product))

            #assigning list variables for property-editing functionality
            if prop_sets is not None:
                for k,v in prop_sets:
                    group_box = QtGui.QGroupBox()
                    group_box.setTitle(k)
                    group_layout = QtGui.QVBoxLayout()
                    group_box.setLayout(group_layout)

                    for name, value in v.items():
                        prop_name = str(name)

                        value_str = value
                        if hasattr(value_str, "wrappedValue"):
                            value_str = value_str.wrappedValue

                        if isinstance(value_str, unicode):
                            value_str = value_str.encode('utf-8')
                        else:
                            value_str = str(value_str)

                        if hasattr(value, "is_a"):
                            type_str = "<i>(%s)</i>" % value.is_a()
                        else:
                            type_str = "\t"

                        #from here on: functionality to adapt properties
                        #collects text from input at propertypanel
                        def textchanged(text):
                            textlist.append(str(text))


                        #binds the new value of the property to the property's name together in a (single-pair) dictionary and adds them to the final list 'changelist', which is going to be used to write to a new file
                        def dict_binder(prop):
                            new_value=textlist[-1]
                            d={}
                            d[prop]=new_value
                            recognitionlist=[product,prop,new_value]
                            prod_pname_text.append(recognitionlist)
                            product_props={product:[d]}
                            definitiveproplist.append(product_props)

                        if hasattr(value, "is_a"):
                            if len(str(value_str))>0:
                                pn=QLabel(prop_name+' '+ type_str + ' = ' + value_str)
                            else:
                                pn=QLabel(prop_name+' '+type_str)
                        else:
                            pn=QLabel(prop_name+' = '+value_str)

                        inputline=QLineEdit()
                        inputline.setFixedWidth(150)
                        for item in prod_pname_text:
                            prod=item[0]
                            pname=item[1]
                            pvalue=item[2]
                            if prod == product and pname==prop_name:
                                inputline.setText(str(pvalue))
                        inputline.setAlignment(Qt.AlignRight)
                        inputline.textChanged.connect(lambda text:textchanged(text))
                        inputline.returnPressed.connect(lambda prop=prop_name: dict_binder(prop))
                        prop_line=QHBoxLayout()
                        pn.setWordWrap(True)
                        prop_line.addWidget(pn)
                        prop_line.addWidget(inputline)

                        group_layout.addLayout(prop_line)

                    self.scrollLayout.addWidget(group_box)

                self.scrollLayout.addStretch()

            else:
                label = QtGui.QLabel("No IfcPropertySets associated with selected entity instance" )
                self.scrollLayout.addWidget(label)

            #from here: part to add propertysets to ifcfile
            retr_prop_name=[]
            retr_prop_desc=[]
            retr_prop_nomv=["IfcText"]
            retr_prop_wv=[]
            retr_prop_unit=[]
            retr_setname=[]

            #more possibilities for types of IfcPropertySingleValues can be added in this list
            simplevalues=[" ","IfcInteger","IfcReal","IfcBoolean","IfcIdentifier","IfcText","IfcLabel","IfcLogical"]

            propertylist=[]
            definitive_propsetlist=[]

            def name_changed(text):
                retr_prop_name.append(text)
            def desc_changed(text):
                retr_prop_desc.append(text)
            def nomv_changed(index):
                i=int(index)
                nominalvalue=simplevalues[i]
                retr_prop_nomv.append(nominalvalue)
            def wv_changed(text):
                retr_prop_wv.append(text)
            def unit_changed(text):
                retr_prop_unit.append(text)
            def setname_changed(text):
                retr_setname.append(text)

            def return_prop():
                newname=retr_prop_name[-1]
                try: newdesc=retr_prop_desc[-1]
                except: newdesc="None"
                newnomv=retr_prop_nomv[-1]
                try: newwv=retr_prop_wv[-1]
                except: newwv="None"
                try: newunit=retr_prop_unit[-1]
                except: newunit="None"

                #here, the actual list made and stored into 'propertylist'
                new_ifc_prop=[str(newname),str(newdesc),str(newnomv),str(newwv),str(newunit)]
                propertylist.append(new_ifc_prop)
                add_propset()

            def bind_propset_to_product():
                setname=str(retr_setname[-1])
                customset={setname:definitive_propsetlist[-1]}
                product_set={product:customset}
                finalcproplist.append(product_set)

                #clear the values to prepare the system for a new propertyset
                retr_prop_name[:]=[]
                retr_prop_desc[:]=[]
                retr_prop_nomv[:]=[]
                retr_prop_wv[:]=[]
                retr_prop_unit[:]=[]
                retr_setname[:]=[]

                win.close()

            def group_cprops():
                littlelist=[]
                for item in propertylist:
                    littlelist.append(item)
                definitive_propsetlist.append(littlelist)
                propertylist[:]=[]
                #propertylist_display[:]=[]

            def b_clicked():
                prop_dial=QDialog()
                vbox=QVBoxLayout()
                dial_layout=QFormLayout()
                vbox.addLayout(dial_layout)
                prop_dial.setLayout(vbox)

                L1=QLabel("Name")
                T1=QLineEdit()
                T1.textChanged.connect(name_changed)
                dial_layout.addRow(L1,T1)

                L2=QLabel("Description")
                T2=QLineEdit()
                T2.textChanged.connect(desc_changed)
                dial_layout.addRow(L2,T2)

                L3=QLabel("Nominalvalue")
                T3=QComboBox()
                T3.addItems(simplevalues)
                T3.activated.connect(nomv_changed)
                dial_layout.addRow(L3,T3)

                L4=QLabel("WrappedValue")
                T4=QLineEdit()
                T4.textChanged.connect(wv_changed)
                dial_layout.addRow(L4,T4)

                L5=QLabel("Unit")
                T5=QLineEdit()
                T5.setText("None")
                T5.setReadOnly(True)
                T5.textChanged.connect(unit_changed)
                dial_layout.addRow(L5,T5)

                prop_dial.setGeometry(500,500,400,100)
                prop_dial.setWindowTitle("Add new Property")

                okbutton=QPushButton("Add")
                okbutton.clicked.connect(return_prop)
                vbox.addWidget(okbutton)

                prop_dial.show()
                sys.exit(app.exec_())

            def add_propset():
                global win
                win = QDialog()
                win_layout=QVBoxLayout(win)

                PsetNameLabel=QLabel("name of new Propertyset: ")
                PsetNameInput=QLineEdit()
                try: PsetNameInput.setText(retr_setname[-1])
                except: pass
                PsetNameInput.textChanged.connect(setname_changed)
                namebox=QFormLayout()
                namebox.addRow(PsetNameLabel,PsetNameInput)
                win_layout.addLayout(namebox)

                prop_group=QtGui.QGroupBox()
                prop_group.setTitle("Properties to add")
                prop_group_layout=QtGui.QVBoxLayout()
                prop_group.setLayout(prop_group_layout)
                for item in propertylist:
                    prop_label=QLabel(str(item))
                    prop_group_layout.addWidget(prop_label)
                win_layout.addWidget(prop_group)

                buttonset=QHBoxLayout()

                new_property= QPushButton()
                new_property.setText("new Property")
                new_property.clicked.connect(b_clicked)
                buttonset.addWidget(new_property)
                buttonset.addStretch()
                ok_button=QPushButton("Apply")
                ok_button.clicked.connect(group_cprops)
                ok_button.clicked.connect(bind_propset_to_product)
                buttonset.addWidget(ok_button)
                win_layout.addLayout(buttonset)

                win.setGeometry(500,500,400,100)
                win.setWindowTitle("Add new propertyset")
                win.show()
                sys.exit(app.exec_())

            new_propset=QPushButton("Add Propertyset")
            new_propset.clicked.connect(add_propset)
            self.scrollLayout.addWidget(new_propset)

            #functionality for adding semantic information
            retr_easyQueryText=[]
            retr_limit=[]
            lastSPARQLvariables=[]
            radioButtonstate=[True]
            radioButtonstate2=["True"]

            def easyQueryText(text):
                retr_easyQueryText.append(text)
            def easyRetrieveLimit(text):
                retr_limit.append(text)
            def radioButtonChecker(b):
                radioButtonstate.append(b)
            def radioButtonChecker2(b):
                radioButtonstate2.append(str(b))
            def startQuery(querytext,db):
                print(db)
                if str(db[-1]) != str(db[-2]):
                    global g
                    g=rdflib.Graph()
                    global graphURI
                    graphURI=str(db[-1])
                    try:
                        g.parse(graphURI)
                        print("parsed successfully")
                    except:
                        try:
                            g.parse(graphURI,format="ttl")
                            print("parsed successfully")
                        except:
                            try:
                                g.parse(graphURI,format="nt")
                                print("parsed successfully")
                            except:
                                print('\n ERROR: IfcOpenShell was not able to use',graphURI,'as a graph\n')
                else:
                    pass

                whichQuery=radioButtonstate[-1]
                if whichQuery==True:
                    searchedLabel=str('"'+retr_easyQueryText[-1]+'"')
                    try:
                        definedLimit=str(retr_limit[-1])
                        queryString=str('SELECT DISTINCT ?label ?URI WHERE {?URI rdfs:label ?label .FILTER(contains(?label,'+searchedLabel+'))} '+'LIMIT '+definedLimit)
                        split_query_to_retrieve_variables=queryString.split('WHERE')
                        firstPartOfQuery=split_query_to_retrieve_variables[0].split(' ')
                        SPARQLvariables=[]
                        for item in firstPartOfQuery:
                            if len(item)>0:
                                if item[0]=='?':
                                    item=item[1:]
                                    SPARQLvariables.append(item)
                        lastSPARQLvariables.append(SPARQLvariables)
                        qres = g.query(queryString)

                    except:
                        queryString=str('SELECT DISTINCT ?label ?URI WHERE {?URI rdfs:label ?label .FILTER(contains(?label,'+searchedLabel+'))}')
                        split_query_to_retrieve_variables=queryString.split('WHERE')
                        firstPartOfQuery=split_query_to_retrieve_variables[0].split(' ')
                        SPARQLvariables=[]
                        for item in firstPartOfQuery:
                            if len(item)>0:
                                if item[0]=='?':
                                    item=item[1:]
                                    SPARQLvariables.append(item)
                        lastSPARQLvariables.append(SPARQLvariables)
                        qres = g.query(queryString)

                else:
                    queryString=str(querytext[-1])
                    print(queryString)
                    try:
                        qres=g.query(queryString)
                        split_query_to_retrieve_variables=queryString.split('WHERE')
                        split_query_to_retrieve_variables=str(split_query_to_retrieve_variables[0]).replace('\n',' ')
                        firstPartOfQuery=split_query_to_retrieve_variables.split(' ')
                        SPARQLvariables=[]
                        for item in firstPartOfQuery:
                            if len(item)>0:
                                if item[0]=='?':
                                    item=item[1:]
                                    SPARQLvariables.append(item)
                        lastSPARQLvariables.append(SPARQLvariables)

                    except:
                        qres=['empty']
                        print('no valid SPARQL query was entered or no results were found')


                global semanticSearch
                semanticSearch=qres
            retr_semSetName=[]
            def semSetName_changed(text):
                retr_semSetName.append(text)
            def group_semcprops(plist,i):
                prop_or_ref=radioButtonstate2[-1]
                if prop_or_ref=="True":
                    index=int(i[-1])
                    semlittlelist=[]
                    for semprop in plist[index]:
                        semlittlelist.append(semprop)
                    definitive_propsetlist.append(semlittlelist)
                else: pass
            def selected_reference(rlist,i):
                prop_or_ref=radioButtonstate2[-1]
                if prop_or_ref=="False":
                    index=int(i[-1])
                    item=rlist[index]
                    URIwithProduct=(item,str(product))
                    selected_referencelist.append(URIwithProduct)
                else: pass
            def bind_sempropset_to_product():
                prop_or_ref=radioButtonstate2[-1]
                if prop_or_ref=="True":
                    sem_setname=str(retr_semSetName[-1])
                    customsemset={sem_setname:definitive_propsetlist[-1]}
                    product_semset={product:customsemset}
                    finalcproplist.append(product_semset)
                else: pass

                #clear the values to prepare the system for a new propertyset
                retr_semSetName[:]=[]
                win.close()

            #functionality to add the results from a SPARQL query to an IfcPropertySet or an IfcExternalReference
            def add_semantic_propset():
                print(lastSPARQLvariables[-1])
                global win
                win=QDialog()
                QueryDialog_layout=QHBoxLayout(win)
                Subdivision_layout=QVBoxLayout()

                Stack_prop=QStackedWidget()
                Stack_ref=QStackedWidget()
                leftlist=QListWidget()
                leftlist.setMinimumWidth(400)
                QueryDialog_layout.addWidget(leftlist)
                QueryDialog_layout.addLayout(Subdivision_layout)

                #UI to get the name and description for the new ifcPropertyset
                pset_name_layout=QFormLayout()
                PSetNameLabel=QLabel("Name of new Propertyset: ")
                PSetNameInput=QLineEdit()
                PSetNameInput.setMinimumWidth(200)
                PSetNameInput.setMaximumWidth(500)
                PSetNameInput.setAlignment(Qt.AlignRight)
                PSetNameInput.textChanged.connect(semSetName_changed)
                pset_name_layout.addRow(PSetNameLabel,PSetNameInput)

                semPropertybox=QGroupBox()
                semPropertybox.setTitle("IfcPropertyset")
                intermediate_layout_prop=QHBoxLayout()
                Subdivision_layout.addLayout(intermediate_layout_prop)
                layoutForStack_prop=QVBoxLayout()
                prop_button=QRadioButton()
                prop_button.setChecked(True)
                prop_button.toggled.connect(radioButtonChecker2)
                intermediate_layout_prop.addWidget(prop_button)
                layoutForStack_prop.addLayout(pset_name_layout)
                layoutForStack_prop.addWidget(Stack_prop)
                semPropertybox.setLayout(layoutForStack_prop)
                intermediate_layout_prop.addWidget(semPropertybox)

                semReferencebox=QGroupBox()
                semReferencebox.setTitle("IfcExternalReference")
                intermediate_layout_ref=QHBoxLayout()
                Subdivision_layout.addLayout(intermediate_layout_ref)
                layoutForStack_ref=QHBoxLayout()
                ref_button=QRadioButton()
                ref_button.setChecked(False)
                intermediate_layout_ref.addWidget(ref_button)
                layoutForStack_ref.addWidget(Stack_ref)
                semReferencebox.setLayout(layoutForStack_ref)
                intermediate_layout_ref.addWidget(semReferencebox)

                global semPropertylist
                semPropertylist=[]

                global referencelist
                referencelist=[]

                Querylength=range(len(semanticSearch))
                for row,index in zip(semanticSearch,Querylength):
                    rowStack_prop=QWidget()
                    rowStack_ref=QWidget()
                    Stack_prop.addWidget(rowStack_prop)
                    Stack_ref.addWidget(rowStack_ref)
                    firstResource=list(row)[0]
                    leftlist.insertItem(index,firstResource)

                    def stackUI_propset():
                        infolayout=QVBoxLayout()
                        rowStack_prop.setLayout(infolayout)
                        intermediate_list=[]
                        QueryVars=lastSPARQLvariables[-1]

                        for item,no in zip(row,range(len(row))):
                            no=int(no)
                            proposedProperty_displayed=str("IFCPROPERTYSINGLEVALUE('"+QueryVars[no]+"','"+QueryVars[no]+"',IFCTEXT('"+item+"'),$)")
                            new_ifc_semprop=[QueryVars[no],QueryVars[no],'IFCTEXT',str(item),'$']
                            intermediate_list.append(new_ifc_semprop)
                            itemLabel=QLabel(proposedProperty_displayed)
                            infolayout.addWidget(itemLabel)

                        GraphProperty_displayed=str("IFCPROPERTYSINGLEVALUE('Queried Graph','URI or local folder of the queried Graph',IFCTEXT('"+graphURI+"'),$)")
                        GraphProperty=['URI of the graph','URI or local folder of the queried Graph','IFCTEXT',graphURI,'$']
                        intermediate_list.append(GraphProperty)
                        graphPropLabel=QLabel(GraphProperty_displayed)
                        infolayout.addWidget(graphPropLabel)
                        semPropertylist.append(intermediate_list)

                    stackUI_propset()

                    def stackUI_reference():
                        infolayout=QVBoxLayout()
                        rowStack_ref.setLayout(infolayout)
                        intermediate_list=[]
                        for item,no in zip(row,range(len(row))):
                            if type(item)==rdflib.term.URIRef:
                                proposedref_displayed=str("IFCEXTERNALREFERENCE("+str(item)+",$,$)")

                                intermediate_list.append(item)
                                ref_label=QLabel(proposedref_displayed)
                                infolayout.addWidget(ref_label)
                        referencelist.append(intermediate_list)

                    stackUI_reference()

                currentIndexlist=[0]

                def stackDisplay(i):
                    Stack_prop.setCurrentIndex(i)
                    Stack_ref.setCurrentIndex(i)
                    currentIndexlist[0]=i

                applybutton=QPushButton("Apply")
                applybutton.clicked.connect(lambda state, plist=semPropertylist,i=currentIndexlist: group_semcprops(plist,i))
                applybutton.clicked.connect(bind_sempropset_to_product)
                applybutton.clicked.connect(lambda state, rlist=referencelist,i=currentIndexlist: selected_reference(rlist,i))

                def cleanup_semproplist():
                    semPropertylist[:]=[]

                applybutton.clicked.connect(cleanup_semproplist)
                Subdivision_layout.addWidget(applybutton)

                leftlist.currentRowChanged.connect(stackDisplay)
                win.setGeometry(500,500,900,150)
                win.setWindowTitle("Results")
                win.show()
                sys.exit(app.exec_())

            #interface for querying external datasets
            def Perform_semantic_search():
                win = QDialog()
                win_layout=QVBoxLayout(win)

                datasetpickline=QHBoxLayout()
                showURI=str("Database to be queried: ")
                URIlabel=QLabel(showURI)
                datasetpickline.addWidget(URIlabel)
                datasetManualInput=QLineEdit()
                try:
                    datasetManualInput.setText(datasetList[-1])
                except:
                    pass
                datasetpickline.addWidget(datasetManualInput)

                def pick_local_dataset():
                    global datasetFolder
                    datasetFolder=QtGui.QFileDialog.getOpenFileName(None, 'Choose dataset', '', "(*.rdf *.owl *.ttl *.nt)")
                    print(datasetFolder)
                    datasetManualInput.setText(str(datasetFolder))
                    win.raise_()

                def retrieve_dataset_from_line():
                    finalDataSet=datasetManualInput.text()
                    datasetList.append(finalDataSet)

                localDatasetButton=QPushButton(" Local Database ")
                datasetpickline.addWidget(localDatasetButton)
                localDatasetButton.clicked.connect(pick_local_dataset)

                win_layout.addLayout(datasetpickline)

                #layout for the easy SPARQL query option (performs search based on label)
                easyQueryLayout=QHBoxLayout()
                win_layout.addLayout(easyQueryLayout)

                easyRadioButton=QRadioButton()
                easyRadioButton.setChecked(True)
                easyRadioButton.toggled.connect(radioButtonChecker)
                easyQueryLayout.addWidget(easyRadioButton)

                easyGroupBox=QGroupBox()
                easyGroupBox.setTitle("Search with label")
                easyQueryLayout.addWidget(easyGroupBox)

                easySPARQLLayout=QVBoxLayout()
                containLayout=QHBoxLayout()
                easySPARQLLayout.addLayout(containLayout)
                limitLayout=QHBoxLayout()
                easySPARQLLayout.addLayout(limitLayout)

                easyGroupBox.setLayout(easySPARQLLayout)
                easyDescription=QLabel("Label contains: ")
                easyInputLine=QLineEdit()
                easyInputLine.setFixedWidth(200)
                easyInputLine.textChanged.connect(easyQueryText)
                containLayout.addWidget(easyDescription)
                containLayout.addStretch()
                containLayout.addWidget(easyInputLine)

                easyLimitDescription=QLabel("LIMIT:")
                easyLimitLine=QLineEdit()
                easyLimitLine.setValidator(QIntValidator())
                easyLimitLine.setFixedWidth(200)
                easyLimitLine.textChanged.connect(easyRetrieveLimit)
                limitLayout.addWidget(easyLimitDescription)
                limitLayout.addStretch()
                limitLayout.addWidget(easyLimitLine)

                #layout for the advanced SPARQL query option
                customQueryLayout=QHBoxLayout()
                win_layout.addLayout(customQueryLayout)

                customRadioButton=QRadioButton()
                customRadioButton.setChecked(False)
                customQueryLayout.addWidget(customRadioButton)

                customGroupBox=QGroupBox()
                customGroupBox.setTitle("Search with custom SPARQL query")

                customQueryLayout.addWidget(customGroupBox)
                QueryBox=QVBoxLayout()
                customGroupBox.setLayout(QueryBox)

                finalquerytext=[]
                def retrieve_query():
                    SPARQLquery=SPARQLInput.toPlainText()
                    finalquerytext.append(SPARQLquery)

                SPARQLInput=QTextEdit()
                QueryBox.addWidget(SPARQLInput)
                notelabel=QLabel("NOTE: \t 1) Variables in the SPARQL query will be used for Name and Description of the IfcPropertySingleValue\n \t 2) First variable is also used for displaying results")
                QueryBox.addWidget(notelabel)

                #button to start querying the dataset
                QueryButton=QPushButton("Start Query")
                win_layout.addWidget(QueryButton)
                QueryButton.clicked.connect(retrieve_dataset_from_line)
                QueryButton.clicked.connect(retrieve_query)
                QueryButton.clicked.connect(lambda state, querytext=finalquerytext,db=datasetList:startQuery(querytext,db))
                QueryButton.clicked.connect(add_semantic_propset)
                QueryButton.clicked.connect(lambda: win.close())

                win.setGeometry(500,500,400,100)
                win.setWindowTitle("Perform semantic search")
                win.show()
                sys.exit(app.exec_())

            semantic_propset=QPushButton("Add Semantic Propertyset")
            semantic_propset.clicked.connect(Perform_semantic_search)
            self.scrollLayout.addWidget(semantic_propset)

        def load_file(self, f, **kwargs):
            for p in f.by_type("IfcProduct"):
                propsets = []

                def process_pset(prop_def):
                    if prop_def is not None:
                        prop_set_name = prop_def.Name
                        props = {}
                        if prop_def.is_a("IfcElementQuantity"):
                            for q in prop_def.Quantities:
                                if q.is_a("IfcPhysicalSimpleQuantity"):
                                    props[q.Name]=q[3]
                        elif prop_def.is_a("IfcPropertySet"):
                            for prop in prop_def.HasProperties:
                                if prop.is_a("IfcPropertySingleValue"):
                                    props[prop.Name]=prop.NominalValue
                        else:
                            # Entity introduced in IFC4
                            # prop_def.is_a("IfcPreDefinedPropertySet"):
                            for prop in range(4, len(prop_def)):
                                props[prop_def.attribute_name(prop)]=prop_def[prop]
                        return prop_set_name, props

                try:
                    for is_def_by in p.IsDefinedBy:
                        if is_def_by.is_a("IfcRelDefinesByProperties"):
                            propsets.append(process_pset(is_def_by.RelatingPropertyDefinition))
                        elif is_def_by.is_a("IfcRelDefinesByType"):
                            type_psets = is_def_by.RelatingType.HasPropertySets
                            if type_psets is None: continue
                            for propset in type_psets:
                                propsets.append(process_pset(propset))
                except Exception, e:
                    import traceback
                    print("failed to load properties: {}".format(e))
                    traceback.print_exc()

                if len(propsets):
                    self.prop_dict[str(p)] = propsets

            print ("property set dictionary has {} entries".format(len(self.prop_dict)))

    class customPanel(QtGui.QWidget):

        def __init__(self):
            QtGui.QWidget.__init__(self)
            self.layout= QtGui.QVBoxLayout(self)
            self.setLayout(self.layout)
            self.scroll = QtGui.QScrollArea(self)
            self.layout.addWidget(self.scroll)
            self.scroll.setWidgetResizable(True)
            self.scrollContent = QtGui.QWidget(self.scroll)
            self.scrollLayout = QtGui.QVBoxLayout(self.scrollContent)
            self.scrollContent.setLayout(self.scrollLayout)
            self.scroll.setWidget(self.scrollContent)
            self.prop_dict = {}

            label = QtGui.QLabel("Testpaneel")

            self.scrollLayout.addWidget(label)
        #triggered by selection event in either component of parent
        def select(self, product):

            # Clear the old contents if any
            while self.scrollLayout.count():
                child = self.scrollLayout.takeAt(0)
                if child is not None:
                    if child.widget() is not None:
                        child.widget().deleteLater()

            self.scroll = QtGui.QScrollArea()
            self.scroll.setWidgetResizable(True)

    class viewer(qtViewer3d):

        instanceSelected = QtCore.pyqtSignal([object])

        @staticmethod
        def ais_to_key(ais_handle):
            def yield_shapes():
                ais = ais_handle.GetObject()
                if hasattr(ais, 'Shape'):
                    yield ais.Shape()
                    return
                shp = OCC.AIS.Handle_AIS_Shape.DownCast(ais_handle)
                if not shp.IsNull(): yield shp.Shape()
                return
                mult = ais_handle
                if mult.IsNull():
                    shp = OCC.AIS.Handle_AIS_Shape.DownCast(ais_handle)
                    if not shp.IsNull(): yield shp
                else:
                    li = mult.GetObject().ConnectedTo()
                    for i in range(li.Length()):
                        shp = OCC.AIS.Handle_AIS_Shape.DownCast(li.Value(i+1))
                        if not shp.IsNull(): yield shp
            return tuple(shp.HashCode(1 << 24) for shp in yield_shapes())

        def __init__(self, widget):
            qtViewer3d.__init__(self, widget)
            global viewerself
            viewerself=self
            self.ais_to_product = {}
            self.product_to_ais = {}
            self.counter = 0
            self.window = widget

        def initialize(self):
            self.InitDriver()
            self._display.Select = self.HandleSelection

        def load_file(self, f, setting=None):

            if setting is None:
                setting = settings()
                setting.set(setting.USE_PYTHON_OPENCASCADE, True)

            v = self._display

            t = {0: time.time()}
            def update(dt = None):
                t1 = time.time()
                if t1 - t[0] > (dt or -1):
                    v.FitAll()
                    v.Repaint()
                    t[0] = t1

            terminate = [False]
            self.window.window_closed.connect(lambda *args: operator.setitem(terminate, 0, True))

            t0 = time.time()

            it = iterator(setting, f)
            if not it.initialize():
                return

            old_progress = -1
            while True:
                if terminate[0]: break
                shape = it.get()
                product = f[shape.data.id]
                ais = display_shape(shape, viewer_handle=v)
                ais.GetObject().SetSelectionPriority(self.counter)
                self.ais_to_product[self.counter] = product
                self.product_to_ais[product] = ais
                self.counter += 1
                QtGui.QApplication.processEvents()
                if product.is_a() in {'IfcSpace', 'IfcOpeningElement'}:
                    v.Context.Erase(ais, True)
                progress = it.progress() // 2
                if progress > old_progress:
                    print("\r[" + "#" * progress + " " * (50 - progress) + "]", end="")
                    old_progress = progress
                if not it.next():
                    break
                update(0.2)

            print("\rOpened file in %.2f seconds%s" % (time.time() - t0, " "*25))

            update()

        def select(self, product):
            ais = self.product_to_ais.get(product)
            if ais is None: return
            v = self._display.Context
            v.ClearSelected(False)
            v.SetSelected(ais, True)


        def set_color(self, product, red, green, blue):
            qclr = OCC.Quantity.Quantity_Color(red,green,blue, OCC.Quantity.Quantity_TOC_RGB)
            ais_shape = self.product_to_ais.get(product)
            ais = ais_shape.GetObject()
            ais.SetColor(qclr)
            self.update()

        def get_selection_set(self,model):
           selection_set =[]
           for p in model.by_type("IfcProduct"):
               ais = self.product_to_ais.get(p)
               if ais != None:
                   if self._display.Context.IsSelected(ais):
                       selection_set.append(p)
           return selection_set

        def set_transparency(self, product, transp):
            ais_shape = self.product_to_ais.get(product)
            ais = ais_shape.GetObject()
            ais.SetTransparency(transp)

        def toggle(self, product_or_products, fn):
            if not isinstance(product_or_products, Iterable):
                product_or_products = [product_or_products]
            aiss = list(filter(None, map(self.product_to_ais.get, product_or_products)))
            last = len(aiss) - 1
            for i, ais in enumerate(aiss):
                fn(ais, i == last)

        def toggle_visibility(self, product_or_products, flag):
            v = self._display.Context
            if flag:
                def visibility(ais, last):
                    v.Erase(ais, last)
            else:
                def visibility(ais, last):
                    v.Display(ais, last)
            self.toggle(product_or_products, visibility)

        def toggle_wireframe(self, product_or_products, flag):
            v = self._display.Context
            if flag:
                def wireframe(ais, last):
                    if v.IsDisplayed(ais):
                        v.SetDisplayMode(ais, 0, last)
            else:
                def wireframe(ais, last):
                    if v.IsDisplayed(ais):
                        v.SetDisplayMode(ais, 1, last)
            self.toggle(product_or_products, wireframe)

        def HandleSelection(self, X, Y):
            v = self._display.Context
            v.Select()
            v.InitSelected()
            if v.MoreSelected():
                ais = v.SelectedInteractive()
                inst = self.ais_to_product[ais.GetObject().SelectionPriority()]
                self.instanceSelected.emit(inst)

    class window(QtGui.QMainWindow):

        TITLE = "IfcOpenShell IFC viewer"

        window_closed = QtCore.pyqtSignal([])

        def __init__(self):
            QtGui.QMainWindow.__init__(self)
            self.setWindowTitle(self.TITLE)
            self.menu = self.menuBar()
            self.menus = {}

        def closeEvent(self, *args):
            self.window_closed.emit()

        def add_menu_item(self, menu, label, callback, icon=None, shortcut=None):
            m = self.menus.get(menu)
            if m is None:
                m = self.menu.addMenu(menu)
                self.menus[menu] = m

            if icon:
                a = QtGui.QAction(QtGui.QIcon(icon), label, self)
            else:
                a = QtGui.QAction(label, self)

            if shortcut:
                a.setShortcut(shortcut)

            a.triggered.connect(callback)
            m.addAction(a)

    def makeSelectionHandler(self, component):
        def handler(inst):
            for c in self.components:
                if c != component:
                    c.select(inst)
        return handler

    global colorfunction
    def colorfunction(self):
        viewer=self.canvas
        for entity in f:
            if entity not in MatchingList:
                viewer.toggle_wireframe(entity,1)

        for item in MatchingList:
            viewer.toggle_wireframe(item,0)

    global pick_graph
    def pick_graph(self):
        global GraphFolder
        GraphFolder=QtGui.QFileDialog.getOpenFileName(None, 'Choose dataset', '', "(*.rdf *.owl *.ttl *.nt)")
        self.datasetFolderInput.setText(str(GraphFolder))

    global retrieve_sparql_query
    def retrieve_sparql_query(self):
        SPARQLquery=self.Input_for_Query.toPlainText()
        FinalSPARQLquery.append(SPARQLquery)

    global modelquery
    def modelquery(self):
        global database
        database=str(self.datasetFolderInput.text())
        print(database)
        self.FolderList.append(database)
        Query=str(FinalSPARQLquery[-1])
        print(Query)

        if str(self.FolderList[-1]) != str(self.FolderList[-2]):
            global q
            q=rdflib.Graph()
            try:
                q.parse(database)
                print("parsed successfully")
            except:
                try:
                    q.parse(database,format="ttl")
                    print("parsed successfully")
                except:
                    try:
                        q.parse(database,format="nt")
                        print("parsed successfully")
                    except:
                        print('\n ERROR: not able to use',database,'as a graph\n')
            for triple in q:
                if type(triple[0]) is rdflib.term.URIRef:
                    sub_res=rdflib.resource.Resource(q,triple[0])
                    try:
                        namesub=sub_res.qname()
                    except:
                        namesub=triple[0]
                elif type(triple[0]) is rdflib.term.Literal:
                    namesub=triple[0]

                if type(triple[1]) is rdflib.term.URIRef:
                    pred_res=rdflib.resource.Resource(q,triple[1])
                    try:
                        namepred=pred_res.qname()
                    except:
                        namepred=triple[1]
                elif type(triple[1]) is rdflib.term.Literal:
                    namepred=triple[1]

                if type(triple[2]) is rdflib.term.URIRef:
                    obj_res=rdflib.resource.Resource(q,triple[2])
                    try:
                        nameobj=obj_res.qname()
                    except:
                        nameobj=triple[2]
                elif type(triple[2]) is rdflib.term.Literal:
                    nameobj=triple[2]

                if namesub not in subjectList_model:
                       subjectList_model.append(namesub)
                if namepred not in subjectList_model:
                       predicateList_model.append(namepred)
                if nameobj not in subjectList_model:
                       objectList_model.append(nameobj)


            no_please=['0','1','2','3','4','5','6','7','8','9','-']
            objectList_model_clean = [x for x in objectList_model if len(x) and str(x[0]) not in no_please]

            sorted_subjectList_model=list(sorted(list(set(subjectList_model))))
            sorted_predicateList_model=list(sorted(list(set(predicateList_model))))
            sorted_objectList_model=list(sorted(list(set(objectList_model_clean))))
            self.subjectBox.clear()
            self.predicateBox.clear()
            self.objectBox.clear()
            self.subjectBox.addItems(sorted_subjectList_model)
            self.predicateBox.addItems(sorted_predicateList_model)
            self.objectBox.addItems(sorted_objectList_model)

        global ResultingList
        ResultingList=[]
        ResultingList=q.query(Query)

    global pre_parser
    def pre_parser(self):
            global database
            database=str(self.datasetFolderInput.text())
            print(database)
            self.FolderList.append(database)
            if str(self.FolderList[-1]) != str(self.FolderList[-2]):
                global q
                q=rdflib.Graph()
                try:
                    q.parse(database)
                    print("parsed successfully")
                except:
                    try:
                        q.parse(database,format="ttl")
                        print("parsed successfully")
                    except:
                        try:
                            q.parse(database,format="nt")
                            print("parsed successfully")
                        except:
                            print('\n ERROR: not able to use',database,'as a graph\n')

                for triple in q:
                    if type(triple[0]) is rdflib.term.URIRef:
                        sub_res=rdflib.resource.Resource(q,triple[0])
                        try:
                            namesub=sub_res.qname()
                        except:
                            namesub=triple[0]
                    elif type(triple[0]) is rdflib.term.Literal:
                        namesub=triple[0]

                    if type(triple[1]) is rdflib.term.URIRef:
                        pred_res=rdflib.resource.Resource(q,triple[1])
                        try:
                            namepred=pred_res.qname()
                        except:
                            namepred=triple[1]
                    elif type(triple[1]) is rdflib.term.Literal:
                        namepred=triple[1]

                    if type(triple[2]) is rdflib.term.URIRef:
                        obj_res=rdflib.resource.Resource(q,triple[2])
                        try:
                            nameobj=obj_res.qname()
                        except:
                            nameobj=triple[2]
                    elif type(triple[2]) is rdflib.term.Literal:
                        nameobj=triple[2]

                    if namesub not in subjectList_model:
                           subjectList_model.append(namesub)
                    if namepred not in subjectList_model:
                           predicateList_model.append(namepred)
                    if nameobj not in subjectList_model:
                           objectList_model.append(nameobj)

                no_please=['0','1','2','3','4','5','6','7','8','9','-']
                objectList_model_clean = [x for x in objectList_model if len(x) and str(x[0]) not in no_please]

                sorted_subjectList_model=list(sorted(list(set(subjectList_model))))
                sorted_predicateList_model=list(sorted(list(set(predicateList_model))))
                sorted_objectList_model=list(sorted(list(set(objectList_model_clean))))

                self.subjectBox.clear()
                self.predicateBox.clear()
                self.objectBox.clear()
                self.subjectBox.addItems(sorted_subjectList_model)
                self.predicateBox.addItems(sorted_predicateList_model)
                self.objectBox.addItems(sorted_objectList_model)

            else:
                pass

    global search_for_matches
    def search_for_matches(self):
        del MatchingList[:]
        IfcIndexList=[]
        for result in ResultingList:
            element=str(result[0])
            element_split=element.split("_")
            element_number=str('#'+element_split[-1])
            IfcIndexList.append(element_number)

        for entity in f:
            entity_string=str(entity)
            entity_split=entity_string.split("=")
            entity_number=entity_split[0]
            if entity_number in IfcIndexList:
                MatchingList.append(entity)

        self.resultwindow.clear()
        MatchingListLength=range(len(MatchingList))
        for item,index in zip(MatchingList,MatchingListLength):
            self.resultwindow.insertItem(index,str(item))

    global colornormalizer
    def colornormalizer(self):
        viewer=self.canvas
        for entity in f:
            if entity.is_a("IfcWall"):
                try:
                    viewer.set_color(entity,.8,.8,.8)
                except: pass
            elif entity.is_a("IfcSite"):
                try:
                    viewer.set_color(entity,.75,.8,.65)
                except: pass
            elif entity.is_a("IfcSlab"):
                try:
                    viewer.set_color(entity,.4,.4,.4)
                except: pass
            elif entity.is_a("IfcWallStandardCase"):
                try:
                    viewer.set_color(entity,.9,.9,.9)
                except: pass
            elif entity.is_a("IfcWindow"):
                try:
                    viewer.set_color(entity,.75,.8,.75)
                    viewer.set_transparency(entity,0.8)
                except: pass
            elif entity.is_a("IfcDoor"):
                try:
                    viewer.set_color(entity,.55,.3,.15)
                except: pass
            elif entity.is_a("IfcBeam"):
                try:
                    viewer.set_color(entity,.75,.7,.7)
                except: pass
            elif entity.is_a("IfcRailing"):
                try:
                    viewer.set_color(entity,.65,.6,.6)
                except: pass
            elif entity.is_a("IfcMember"):
                try:
                    viewer.set_color(entity,.65,.6,.6)
                except: pass
            elif entity.is_a("IfcPlate"):
                try:
                    viewer.set_color(entity,.8,.8,.8)
                except: pass
            else:
                try:
                    viewer.set_color(entity,.7,.7,.7)
                except: pass
            viewer.toggle_wireframe(entity,0)

    global insertsubject
    def insertsubject(self):
        subject_text_to_add=self.subjectBox.currentText()
        self.Input_for_Query.insertPlainText(str(subject_text_to_add+' '))

    global insertpredicate
    def insertpredicate(self):
        predicate_text_to_add=self.predicateBox.currentText()
        self.Input_for_Query.insertPlainText(str(predicate_text_to_add+' '))

    global insertobject
    def insertobject(self):
        object_text_to_add=self.objectBox.currentText()
        self.Input_for_Query.insertPlainText(str(object_text_to_add+' '))

    global clear_spoLists
    def clear_spoLists(self):
        if self.FolderList[-1]==self.FolderList[-2]:
            subjectList_model=subjectList_model[:]
            objectList_model=objectList_model[:]
            predicateList_model=predicateList_model[:]

    global whichitem
    def whichitem(self,item):
        viewer=self.canvas
        selectedElement=str(item.text())
        print(selectedElement)

        for entity in f:
            if entity in MatchingList:
                if entity.is_a("IfcWall"):
                    try:
                        viewer.set_color(entity,.8,.8,.8)
                    except: pass
                elif entity.is_a("IfcSite"):
                    try:
                        viewer.set_color(entity,.75,.8,.65)
                    except: pass
                elif entity.is_a("IfcSlab"):
                    try:
                        viewer.set_color(entity,.4,.4,.4)
                    except: pass
                elif entity.is_a("IfcWallStandardCase"):
                    try:
                        viewer.set_color(entity,.9,.9,.9)
                    except: pass
                elif entity.is_a("IfcWindow"):
                    try:
                        viewer.set_color(entity,.75,.8,.75)
                        viewer.toggle_visibility(entity,1)
                        viewer.toggle_wireframe(entity,0)
                        viewer.set_transparency(entity,0)
                    except: pass
                elif entity.is_a("IfcDoor"):
                    try:
                        viewer.set_color(entity,.55,.3,.15)
                    except: pass
                elif entity.is_a("IfcBeam"):
                    try:
                        viewer.set_color(entity,.75,.7,.7)
                    except: pass
                elif entity.is_a("IfcRailing"):
                    try:
                        viewer.set_color(entity,.65,.6,.6)
                    except: pass
                elif entity.is_a("IfcMember"):
                    try:
                        viewer.set_color(entity,.65,.6,.6)
                    except: pass
                elif entity.is_a("IfcPlate"):
                    try:
                        viewer.set_color(entity,.8,.8,.8)
                    except: pass
                else:
                    try:
                        viewer.set_color(entity,.7,.7,.7)
                    except: pass

                if str(entity)==selectedElement:
                    try:
                        viewer.set_color(entity,1,0,0)
                    except: pass

    #definition of the 'internal query' tab happens inside the init (otherwise: problems regarding coloring elements)
    def __init__(self, settings=None):
        QtGui.QApplication.__init__(self, sys.argv)
        self.window = application.window()

        self.tree = application.decomposition_treeview()
        self.tree2 = application.type_treeview()
        self.propview = self.property_table()
        self.custom= self.customPanel()
        self.canvas = application.viewer(self.window)
        self.tabs = QtGui.QTabWidget()


        #######LAYOUT FOR RDF QUERIES#####
        self.rdf_layout= QVBoxLayout()

        #line to specify folder of dataset
        self.datasetpickline=QHBoxLayout()
        self.showURI=str("RDF-version of THIS file: ")
        self.URIlabel=QLabel(self.showURI)
        self.datasetpickline.addWidget(self.URIlabel)
        self.datasetFolderInput=QLineEdit()
        self.datasetpickline.addWidget(self.datasetFolderInput)
        self.localDatasetButton=QPushButton(" ... ")
        self.datasetpickline.addWidget(self.localDatasetButton)
        self.localDatasetButton.clicked.connect(lambda: pick_graph(self))

        #field for SPARQL input
        self.Input_for_Query=QTextEdit()
        self.QueryBox=QGroupBox()
        self.QueryBox.setTitle("Enter SPARQL query: ")
        self.QueryLayout=QVBoxLayout()
        self.QueryLayout.addWidget(self.Input_for_Query)
        self.QueryBox.setLayout(self.QueryLayout)
        self.FolderList=['FirstItem','SecondItem']

        self.preparseLayout=QHBoxLayout()
        self.QueryLayout.addLayout(self.preparseLayout)
        self.preparseButton=QPushButton("pre-parse Graph")
        self.preparseLayout.addWidget(self.preparseButton,1)
        self.preparseButton.clicked.connect(lambda:clear_spoLists(self))
        self.preparseButton.clicked.connect(lambda:pre_parser(self))

        self.preparse_result_layout=QVBoxLayout()
        self.preparseLayout.addLayout(self.preparse_result_layout,3)

        self.subjectLayout=QHBoxLayout()
        self.subjectLabel=QLabel('subjects:')
        self.subjectLayout.addWidget(self.subjectLabel,1)
        self.subjectBox=QComboBox()
        self.subjectBox.activated.connect(lambda: insertsubject(self))
        self.subjectLayout.addWidget(self.subjectBox,3)
        self.preparse_result_layout.addLayout(self.subjectLayout)

        self.predicateLayout=QHBoxLayout()
        self.predicateLabel=QLabel('predicates:')
        self.predicateLayout.addWidget(self.predicateLabel,1)
        self.predicateBox=QComboBox()
        self.predicateBox.activated.connect(lambda: insertpredicate(self))
        self.predicateLayout.addWidget(self.predicateBox,3)
        self.preparse_result_layout.addLayout(self.predicateLayout)

        self.objectLayout=QHBoxLayout()
        self.objectLabel=QLabel('objects:')
        self.objectLayout.addWidget(self.objectLabel,1)
        self.objectBox=QComboBox()
        self.objectBox.activated.connect(lambda: insertobject(self))
        self.objectLayout.addWidget(self.objectBox,3)
        self.preparse_result_layout.addLayout(self.objectLayout)

        #field for results output
        self.resultwindow=QListWidget()
        self.resultwindow.itemDoubleClicked.connect(lambda state,self=self:whichitem(self,state))
        self.ResultBox=QGroupBox()
        self.ResultBox.setTitle("Results: ")
        self.ResultLayout=QVBoxLayout()
        self.ResultLayout.addWidget(self.resultwindow)
        self.ResultBox.setLayout(self.ResultLayout)

        #operating buttons
        self.query_model_button=QtGui.QPushButton('Search')
        self.query_model_button.clicked.connect(lambda:clear_spoLists(self))
        self.query_model_button.clicked.connect(lambda:retrieve_sparql_query(self))
        self.query_model_button.clicked.connect(lambda:modelquery(self))
        self.query_model_button.clicked.connect(lambda:search_for_matches(self))
        self.query_model_button.clicked.connect(lambda: colorfunction(self))
        self.normalize_colors=QPushButton('Default colors')
        self.normalize_colors.clicked.connect(lambda: colornormalizer(self))

        #main layout order
        self.rdf_layout.addLayout(self.datasetpickline)
        self.rdf_layout.addWidget(self.QueryBox)
        self.rdf_layout.addWidget(self.ResultBox)
        self.rdf_layout.addWidget(self.query_model_button)
        self.rdf_layout.addWidget(self.normalize_colors)

        self.Querygroupbox=QGroupBox()
        self.Querygroupbox.setLayout(self.rdf_layout)


        """BACK TO ORIGINAL LAYOUT"""
        self.window.showMaximized()
        splitter = QtGui.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self.tabs)

        self.tabs.setMinimumWidth(450)

        self.tabs.addTab(self.propview, "Properties")
        self.tabs.addTab(self.tree, 'Decomposition')
        self.tabs.addTab(self.tree2, 'Types')
        self.tabs.addTab(self.Querygroupbox, 'Query')

        splitter2 = QtGui.QSplitter(QtCore.Qt.Horizontal)
        splitter2.addWidget(self.canvas)
        self.editor = code_edit(self.canvas, configuration())

        codeDockWidget = QtGui.QDockWidget("Script Code Editor")
        codeDockWidget.setObjectName("codeDockWidget")
        codeDockWidget.setWidget(self.editor)
        #codeDockWidget.setMinimumWidth(200)
        codeDockWidget.setMaximumWidth(600)
        codeDockWidget.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea
                                         | QtCore.Qt.RightDockWidgetArea
                                         | QtCore.Qt.BottomDockWidgetArea
                                         | QtCore.Qt.TopDockWidgetArea)
        self.window.addDockWidget(QtCore.Qt.RightDockWidgetArea, codeDockWidget)

        # splitter2.addWidget(self.editor)
        splitter.addWidget(splitter2)
        splitter.setSizes([200,600])
        splitter2.setSizes([400,200])
        self.window.setCentralWidget(splitter)
        self.canvas.initialize()
        self.components = [self.tree, self.tree2, self.canvas, self.propview, self.editor]
        self.files = {}

        self.window.add_menu_item('File', '&Open', self.browse, shortcut='CTRL+O')
        self.window.add_menu_item('File', '&Save As', save_to_file, shortcut='CTRL+S')
        self.window.add_menu_item('File', '&Close', self.clear, shortcut='CTRL+W')
        self.window.add_menu_item('File', '&Exit', self.window.close, shortcut='ALT+F4')
        self.window.add_menu_item('Extra', '&Added Propertysets',cpropsetsviewer, shortcut=None)

        self.tree.instanceSelected.connect(self.makeSelectionHandler(self.tree))
        self.tree2.instanceSelected.connect(self.makeSelectionHandler(self.tree2))
        self.canvas.instanceSelected.connect(self.makeSelectionHandler(self.canvas))

        for t in [self.tree, self.tree2]:
            t.instanceVisibilityChanged.connect(functools.partial(self.change_visibility, t))
            t.instanceDisplayModeChanged.connect(functools.partial(self.change_displaymode, t))
        # self.window.statusBar().showMessage('Ready')
        self.settings = settings

    def change_visibility(self, tree, inst, flag):
        insts = tree.get_children(inst)
        self.canvas.toggle_visibility(insts, flag)

    def change_displaymode(self, tree, inst, flag):
        insts = tree.get_children(inst)
        self.canvas.toggle_wireframe(insts, flag)

    def start(self):
        self.window.show()
        sys.exit(self.exec_())

    def browse(self):
        filename = QtGui.QFileDialog.getOpenFileName(self.window, 'Open file',".","Industry Foundation Classes (*.ifc)")
        self.load(filename)

    def clear(self):
        self.canvas._display.Context.RemoveAll()
        self.tree.clear()
        self.tree2.clear()
        self.files.clear()

    def load(self, fn):
        if fn in self.files: return
        global f
        f = open_ifc_file(str(fn))
        self.files[fn] = f
        for c in self.components:
            c.load_file(f, setting=self.settings)

if __name__ == "__main__":
    application().start()
