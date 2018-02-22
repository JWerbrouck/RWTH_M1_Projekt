import os, sys
from ifcopenshell.geom.app import application

os.environ['QT_API'] = 'pyqt4'
os.environ['CSF_GraphicShr'] = os.path.dirname(sys.executable)+('\\Lib\\site-packages\\OCC\\libTKOpenGl.dll')
# del os.environ['CSF_GraphicShr']
# subprocess.call('sqsub -np ' + var1 + 'python', shell=True)
app = application
app().start()
