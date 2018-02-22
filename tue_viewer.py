from ifcopenshell.geom.app import  application


from PyQt4 import QtCore, QtGui



class my_app(application):

    
    def __init__(self):
        application.__init__(self)
       # self.window = my_app.window()
        self.window.setWindowTitle("TU Eindhoven IfcOpenShell scripting tool")
        
        self.label = QtGui.QLabel(self.window)
        self.label.setGeometry(QtCore.QRect(40, 140, 361, 511))
        self.label.setSizePolicy(QtGui.QSizePolicy.Preferred,QtGui.QSizePolicy.Preferred)
        self.label.setObjectName("label")
        self.label.setText("logo")
        myPixmap = QtGui.QPixmap('./tu_logo.png')

        self.label.resize(myPixmap.width(),myPixmap.height())
        myScaledPixmap = myPixmap.scaled(self.label.size(), QtCore.Qt.KeepAspectRatio)
        self.label.setPixmap(myScaledPixmap)
        # tb.insertWidget(self.label)
        self.window.statusBar().addWidget(self.label)

        self.ios_label = QtGui.QLabel(self.window)
        self.ios_label.setGeometry(QtCore.QRect(40, 140, 361, 511))
        self.ios_label.setSizePolicy(QtGui.QSizePolicy.Preferred,QtGui.QSizePolicy.Preferred)
        self.ios_label.setObjectName("label")
        self.ios_label.setText("logo")
        myPixmap = QtGui.QPixmap('./ifcopenshell.png')

        self.ios_label.resize(myPixmap.width(),myPixmap.height())
        myScaledPixmap = myPixmap.scaled(self.ios_label.size(), QtCore.Qt.KeepAspectRatio)
        self.ios_label.setPixmap(myScaledPixmap)
        self.window.statusBar().addWidget(self.ios_label)
        
my_app().start()