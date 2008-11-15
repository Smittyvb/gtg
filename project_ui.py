#=== IMPORT ====================================================================
#system imports
import pygtk
pygtk.require('2.0')
import gtk
import gobject
import xml.dom.minidom
import gtk.glade
import datetime, time, sys
import uuid

#our own imports
from task      import Task, Project
from datastore import DataStore
#subfolders are added to the path
sys.path[1:1]=["backends"]
from xml_backend import Backend

#=== OBJECTS ===================================================================

#=== MAIN CLASS ================================================================

class NewProjectDialog:

    def __init__(self, datastore):
        
        #Set the Glade file
        self.gladefile = "gtd-gnome.glade"  
        self.wTree = gtk.glade.XML(self.gladefile, "NewProjectDialog") 
        
        #Get the Main Window, and connect the "destroy" event
        self.window = self.wTree.get_widget("NewProjectDialog")
        #if (self.window):
        #    self.window.connect("destroy", gtk.main_quit)

        #Create our dictionay and connect it
        dic = {
                "on_save_btn_clicked"   : self.on_save_btn_clicked,
                "on_cancel_btn_clicked" : self.on_cancel_btn_clicked
              }
        self.wTree.signal_autoconnect(dic)
        self.ds = datastore
        
    def main(self):
        self.window.show()
        return 0

    def set_on_close_cb(self, cb):
        self.on_close_cb = cb

    def on_save_btn_clicked(self, widget):
        # Extract project name
        tv   = self.wTree.get_widget("project_desc_tv")
        buff = tv.get_buffer()
        text = buff.get_text(buff.get_start_iter(),buff.get_end_iter())
        # Create project
        p = Project(text)
        # Create backend
        bid = uuid.uuid4()
        b   = Backend(str(bid)+".xml")
        b.set_project(p)
        b.sync_project()
        # Register it in datastore
        self.ds.register_backend(b)
        # Register it in datastore
        self.ds.add_project(p, b)
        # Close window
        self.window.destroy()
        # Trigger parent window to do whatever is needed to do
        self.on_close_cb()
        return 0

    def on_cancel_btn_clicked(self, widget):
        self.on_close_cb()
        self.window.destroy()


