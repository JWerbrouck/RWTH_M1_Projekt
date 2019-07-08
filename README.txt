This repository contains an adaptation of the IfcOpenShell TUEviewer (downloadable at https://github.com/jakob-beetz/IfcOpenShellScriptingTutorial). The code was written within context of the M1 Project Architekturinformatik at RWTH Aachen University, 2017-2018. 

The project links IfcOpenShell with some Linked Data technologies, providing some 'hybrid' solution between EXPRESS ifc and Linked Data technologies (RDF, SPARQL, ...). Learning to code in Python and developing this project happened to be parallel (this is, let's say, my 'HelloWorld' program; so although the functionality is working more or less properly, the coding style could be much better (my apologies for this). 

The entire code adaptation is made in the 'app.py' file (Lib/Site-Packages/IfcOpenShell/geom). Further changes to the original are the installation of rdflib (https://github.com/RDFLib/rdflib) and Sparqlwrapper (https://github.com/RDFLib/sparqlwrapper). However, to minimize installation problems, the whole package is copied to this repository. 

Specifically, the project introduces 4 main functionalities:
	1. Changing already defined IfcPropertySingleValues of element that is selected in the viewer
	2. Adding custom defined IfcPropertySets to the selected element
	3. Querying an external graph (e.g. bsDD) with SPARQL and link the results to the element
		- as an IfcPropertySet
		- as an IfcPropertySingleValue
	4. Querying the triple-based version of the model (with SPARQL) for visualising purposes
	
More information about IfcOpenShell is available at: http://ifcopenshell.org/
