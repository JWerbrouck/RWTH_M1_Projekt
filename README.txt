This repository contains an adaptation of the IfcOpenShell TUEviewer (https://github.com/jakob-beetz/IfcOpenShellScriptingTutorial). The code was written within context of the M1 Project Architekturinformatik at RWTH Aachen. 

The project links IfcOpenShell with some Linked Data technologies, providing some 'hybrid' solution between EXPRESS ifc and Linked Data technologies (RDF, SPARQL, ...). Learning to code in Python and developing this project happened to be parallel (this is, let's say, my 'HelloWorld' program; so the although the wished functionality is working properly, the coding style could be much better. Actually, the whole adaptation is made in the 'app.py' file (Lib/Site-Packages/IfcOpenShell/geom). Further changes to the original are the installation of rdflib and Sparqlwrapper. However, to minimize installation problems, the whole package is copied to this repository. 

Specifically, the project introduces 4 main functionalities:
	1. Changing already defined IfcPropertySingleValues of element that is selected in the viewer
	2. Adding custom defined IfcPropertySets to the selected element
	3. Querying an external graph (e.g. bsDD) with SPARQL and link the results to the element
		- as an IfcPropertySet
		- as an IfcPropertySingleValue
	4. Querying the triple-based version of the model (with SPARQL) for visualising very specific queries
	
More information about IfcOpenShell is available at: http://ifcopenshell.org/
