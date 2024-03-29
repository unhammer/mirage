#!/usr/bin/python2
# $HeadURL$
# $Id$

__version__ = "1.0-svn"
__appname__ = "Mirage"
__license__ = """
Mirage, a fast GTK+ Image Viewer
Copyright 2007 Scott Horowitz <stonecrest@gmail.com>
Copyright 2010-2011 Fredric Johansson <fredric.miscmail@gmail.com>

This file is part of Mirage.

Mirage is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

Mirage is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import traceback
import pygtk
pygtk.require('2.0')
import gtk
import os, sys, getopt, string, gc
import random, urllib, gobject, gettext, locale
import stat, time, subprocess, shutil, filecmp
import tempfile, socket, threading, copy
from fractions import Fraction
import json

gettext.install("mirage", unicode=1)

try:
	import mirage_numacomp as numacomp
	HAVE_NUMACOMP = True
except:
	HAVE_NUMACOMP = False
	print _("mirage_numacomp.so not found, unable to do numerical aware sorting.")

try:
	import hashlib
	HAS_HASHLIB = True
except:
	HAS_HASHLIB= False
	import md5
try:
	import imgfuncs
	HAS_IMGFUNCS = True
except:
	HAS_IMGFUNCS = False
	print _("imgfuncs.so module not found, rotating/flipping images will be disabled.")
try:
	import xmouse
	HAS_XMOUSE = True
except:
	HAS_XMOUSE = False
	print _("xmouse.so module not found, some screenshot capabilities will be disabled.")

try:
	import pyexiv2
	HAS_EXIF = True
except:
	HAS_EXIF = False
	print _("pyexiv2 module not found, exifdata reading/writing are disabled")

try:
	import gconf
except:
	pass

if gtk.gtk_version < (2, 10, 0):
	sys.stderr.write(_("Mirage requires GTK+ %s or newer..\n") % "2.10.0")
	sys.exit(1)
if gtk.pygtk_version < (2, 12, 0):
	sys.stderr.write(_("Mirage requires PyGTK %s or newer.\n") % "2.12.0")
	sys.exit(1)

def valid_int(inputstring):
	try:
		x = int(inputstring)
		return True
	except:
		return False

class Base:

	def __init__(self):
		gtk.gdk.threads_init()

		# Constants
		self.open_mode_smart = 0
		self.open_mode_fit = 1
		self.open_mode_1to1 = 2
		self.open_mode_last = 3
		self.min_zoomratio = 0.02

		# Current image:
		self.curr_img_in_list = 0
		# This is the actual pixbuf that is loaded in Mirage. This will
		# usually be the same as self.curr_img_in_list except for scenarios
		# like when the user presses 'next image' multiple times in a row.
		# In this case, self.curr_img_in_list will increment while
		# self.loaded_img_in_list will retain the current loaded image.
		self.loaded_img_in_list = -2
		self.currimg = ImageData(index=0)
		# Next preloaded image:
		self.nextimg = ImageData(index=-1)
		# Previous preloaded image:
		self.previmg = ImageData(index=-1)

		# Create a dictionary with all settings the users can do in the interface
		self.usettings = {}

		# Window settings
		self.usettings['window_width'] = 600
		self.usettings['window_height'] = 400
		self.usettings['toolbar_show'] = True
		self.usettings['thumbpane_show'] = True
		self.usettings['statusbar_show'] = True

		# Settings, Behavior
		self.usettings['open_mode'] = self.open_mode_smart
		self.usettings['last_mode'] = self.open_mode_smart
		self.usettings['open_all_images'] = True # open all images in the directory(ies)
		self.usettings['open_hidden_files'] = False
		self.usettings['use_numacomp'] = False
		self.usettings['case_numacomp'] = False
		self.usettings['use_last_dir'] = True
		self.usettings['last_dir'] = os.path.expanduser("~")
		self.usettings['fixed_dir'] = os.path.expanduser("~")

		# Settings, Navigation
		self.usettings['listwrap_mode'] = 0	# 0=no, 1=yes, 2=ask
		self.usettings['preloading_images'] = True

		# Settings, Interface
		self.usettings['simple_bgcolor'] = False
		self.usettings['bgcolor'] = {'r':0, 'g':0, 'b': 0}
		self.usettings['thumbnail_size'] = 128	# Default to 128 x 128
		self.usettings['start_in_fullscreen'] = False

		# Settings, Slideshow
		self.usettings['slideshow_delay'] = 1	# seconds
		self.usettings['disable_screensaver'] = False
		self.usettings['slideshow_in_fullscreen'] = False
		self.usettings['slideshow_random'] = False

		# Settings, Editing:
		self.usettings['zoomvalue'] = 2
		self.usettings['savemode'] = 2
		self.usettings['quality_save'] = 90
		self.usettings['confirm_delete'] = True

		# Action settings
		self.usettings['action_names'] = [_("Open in GIMP"), _("Create Thumbnail"), _("Create Thumbnails"), _("Move to Favorites")]
		self.usettings['action_shortcuts'] = ["<Control>e", "<Alt>t", "<Control><Alt>t", "<Control><Alt>f"]
		self.usettings['action_commands'] = ["gimp %F", "convert %F -thumbnail 150x150 %Pt_%N.jpg", "convert %F -thumbnail 150x150 %Pt_%N.jpg", "mkdir -p ~/mirage-favs; mv %F ~/mirage-favs; [NEXT]"]
		self.usettings['action_batch'] = [False, False, True, False]

		# Determine config dir, first try the environment variable XDG_CONFIG_HOME
		# according to XDG specification and as a fallback use ~/.config/mirage
		self.config_dir = (os.getenv('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')) + '/mirage'
		# Load config from disk:
		self.read_config_and_set_settings()
		# Set the bg color variable
		bgc = self.usettings['bgcolor']
		self.bgcolor = gtk.gdk.Color(red=bgc['r'], green=bgc['g'], blue=bgc['b'])
		
		self.going_random = False
		self.fullscreen_mode = False
		self.opendialogpath = ""
		self.zoom_quality = gtk.gdk.INTERP_BILINEAR
		self.recursive = False
		self.verbose = False
		self.image_loaded = False
		self.image_list = []
		self.firstimgindex_subfolders_list = []
		self.user_prompt_visible = False	# the "wrap?" prompt
		self.slideshow_mode = False
		self.slideshow_controls_visible = False	# fullscreen slideshow controls
		self.controls_moving = False
		self.updating_adjustments = False
		self.closing_app = False
		self.onload_cmd = None
		self.searching_for_images = False
		self.preserve_aspect = True
		self.ignore_preserve_aspect_callback = False
		self.image_modified = False
		self.image_zoomed = False
		self.running_custom_actions = False
		self.merge_id = None
		self.actionGroupCustom = None
		self.merge_id_recent = None
		self.actionGroupRecent = None
		
		self.thumbnail_sizes = ["128", "96", "72", "64", "48", "32"]
		
		self.thumbnail_loaded = []
		self.thumbpane_updating = False
		self.usettings['recentfiles'] = ["", "", "", "", ""]
		self.usettings['screenshot_delay'] = 2
		self.thumbpane_bottom_coord_loaded = 0
		self.no_sort = False

		# Read any passed options/arguments:
		try:
			opts, args = getopt.getopt(sys.argv[1:], "hRvVsfno:", ["help", "version", "recursive", "verbose", "slideshow", "fullscreen", "no-sort", "onload="])
		except getopt.GetoptError:
			# print help information and exit:
			self.print_usage()
			sys.exit(2)
		# If options were passed, perform action on them.
		go_into_fullscreen = False
		start_slideshow = False
		if opts != []:
			for o, a in opts:
				if o in ("-v", "--version"):
					self.print_version()
					sys.exit(2)
				elif o in ("-h", "--help"):
					self.print_usage()
					sys.exit(2)
				elif o in ("-R", "--recursive"):
					self.recursive = True
				elif o in ("-V", "--verbose"):
					self.verbose = True
				elif o in ("-f", "--fullscreen"):
					go_into_fullscreen = True
				elif o in ("-s", "--slideshow", "-f", "--fullscreen"):
					start_slideshow = True
				elif o in ("-n", "--no-sort"):
					self.no_sort = True
				elif o in ("-o", "--onload"):
					self.onload_cmd = a
				else:
					self.print_usage()
					sys.exit(2)

		# slideshow_delay is the user's preference, whereas curr_slideshow_delay is
		# the current delay (which can be changed without affecting the 'default')
		self.curr_slideshow_delay = self.usettings['slideshow_delay']
		# Same for randomization:
		self.curr_slideshow_random = self.usettings['slideshow_random']

		# Find application images/pixmaps
		self.resource_path_list = False

		self.blank_image = gtk.gdk.pixbuf_new_from_file(self.find_path("mirage_blank.png"))

		# Define the main menubar and toolbar:
		self.iconfactory = gtk.IconFactory()
		icon = gtk.gdk.pixbuf_new_from_file(self.find_path('stock_leave-fullscreen.png'))
		self.iconfactory.add('leave-fullscreen', gtk.IconSet(icon))
		icon = gtk.gdk.pixbuf_new_from_file(self.find_path('stock_fullscreen.png'))
		self.iconfactory.add('fullscreen', gtk.IconSet(icon))
		self.iconfactory.add_default()
		try:
			test = gtk.Button("", gtk.STOCK_LEAVE_FULLSCREEN)
			leave_fullscreen_icon = gtk.STOCK_LEAVE_FULLSCREEN
			fullscreen_icon = gtk.STOCK_FULLSCREEN
		except:
			# This will allow gtk 2.6 users to run Mirage
			leave_fullscreen_icon = 'leave-fullscreen'
			fullscreen_icon = 'fullscreen'
		# Note. Stock items intentionally set to None to use standard stock defaults
		actions = (
			('FileMenu', None, _('_File')),
			('EditMenu', None, _('_Edit')),
			('ViewMenu', None, _('_View')),
			('GoMenu', None, _('_Go')),
			('HelpMenu', None, _('_Help')),
			('ActionSubMenu', None, _('Custom _Actions')),
			('Open Image', gtk.STOCK_FILE, _('_Open Image...'), None, _('Open Image'), self.open_file),
			('Open Remote Image', gtk.STOCK_NETWORK, _('Open _Remote image...'), None, _('Open Remote Image'), self.open_file_remote),
			('Open Folder', gtk.STOCK_DIRECTORY, _('Open _Folder...'), '<Ctrl>F', _('Open Folder'), self.open_folder),
			('Reload', None, _('Reload'), '<Ctrl>F5', _('Reload'), self.reload),
			('Save', gtk.STOCK_SAVE, _('_Save Image'), None, None, self.save_image),
			('Save As', gtk.STOCK_SAVE_AS, _('Save Image _As...'), '<Ctrl><Shift>S', None, self.save_image_as),
			('Copy', gtk.STOCK_COPY, _('Copy to Clipboard...'), '<Ctrl>C', None, self.copy_to_clipboard),
			('Crop', None, _('C_rop...'), None, _('Crop Image'), self.crop_image),
			('Resize', None, _('R_esize...'), '<Ctrl>R', _('Resize Image'), self.resize_image),
			('Saturation', None, _('_Saturation...'), None, _('Modify saturation'), self.saturation),
			('Quit', gtk.STOCK_QUIT, None, None, None, self.exit_app),
			('Previous Image', gtk.STOCK_GO_BACK, _('_Previous Image'), 'Left', _('Previous Image'), self.goto_prev_image),
			('Previous Subfolder', gtk.STOCK_MEDIA_REWIND, _('Pre_vious Subfolder'), '<Shift>Left', _('Previous Subfolder'), self.goto_first_image_prev_subfolder),
			('Next Image', gtk.STOCK_GO_FORWARD, _('_Next Image'), 'Right', _('Next Image'), self.goto_next_image),
			('Next Subfolder', gtk.STOCK_MEDIA_FORWARD, _('Ne_xt Subfolder'), '<Shift>Right', _('Next Subfolder'), self.goto_first_image_next_subfolder),
			('Previous2', gtk.STOCK_GO_BACK, _('_Previous'), 'Left', _('Previous'), self.goto_prev_image),
			('Next2', gtk.STOCK_GO_FORWARD, _('_Next'), 'Right', _('Next'), self.goto_next_image),
			('Random Image', None, _('_Random Image'), 'R', _('Random Image'), self.goto_random_image),
			('First Image', gtk.STOCK_GOTO_FIRST, _('_First Image'), 'Home', _('First Image'), self.goto_first_image),
			('Last Image', gtk.STOCK_GOTO_LAST, _('_Last Image'), 'End', _('Last Image'), self.goto_last_image),
			('In', gtk.STOCK_ZOOM_IN, _('Zoom _In'), '<Ctrl>Up', _('Zoom In'), self.zoom_in),
			('Out', gtk.STOCK_ZOOM_OUT, _('Zoom _Out'), '<Ctrl>Down', _('Zoom Out'), self.zoom_out),
			('Fit', gtk.STOCK_ZOOM_FIT, _('Zoom To _Fit'), '<Ctrl>1', _('Fit'), self.zoom_to_fit_window_action),
			('1:1', gtk.STOCK_ZOOM_100, _('_1:1'), '<Ctrl>0', _('1:1'), self.zoom_1_to_1_action),
			('Rotate Left', None, _('Rotate _Left'), '<Ctrl>Left', _('Rotate Left'), self.rotate_left),
			('Rotate Right', None, _('Rotate _Right'), '<Ctrl>Right', _('Rotate Right'), self.rotate_right),
			('Flip Vertically', None, _('Flip _Vertically'), '<Ctrl>V', _('Flip Vertically'), self.flip_image_vert),
			('Flip Horizontally', None, _('Flip _Horizontally'), '<Ctrl>H', _('Flip Horizontally'), self.flip_image_horiz),
			('About', gtk.STOCK_ABOUT, None, None, None, self.show_about),
			('Contents', gtk.STOCK_HELP, _('_Contents'), 'F1', _('Contents'), self.show_help),
			('Preferences', gtk.STOCK_PREFERENCES, _('Pr_eferences...'), None, _('Preferences'), self.show_prefs),
			('Full Screen', gtk.STOCK_FULLSCREEN, None, 'F11', None, self.enter_fullscreen),
			('Exit Full Screen', leave_fullscreen_icon, _('E_xit Full Screen'), None, _('Exit Full Screen'), self.leave_fullscreen),
			('Start Slideshow', gtk.STOCK_MEDIA_PLAY, _('_Start Slideshow'), 'F5', _('Start Slideshow'), self.toggle_slideshow),
			('Stop Slideshow', gtk.STOCK_MEDIA_STOP, _('_Stop Slideshow'), 'F5', _('Stop Slideshow'), self.toggle_slideshow),
			('Delete Image', gtk.STOCK_DELETE, _('_Delete...'), 'Delete', _('Delete Image'), self.delete_image),
			('Rename Image', None, _('Re_name...'), 'F2', _('Rename Image'), self.rename_image),
			('Take Screenshot', None, _('_Take Screenshot...'), None, _('Take Screenshot'), self.screenshot),
			('Properties', gtk.STOCK_PROPERTIES, _('_Properties...'), None, _('Properties'), self.show_properties),
			('Custom Actions', None, _('_Configure...'), None, _('Custom Actions'), self.show_custom_actions),
			('MiscKeysMenuHidden', None, 'Keys'),
			('Escape', None, '', 'Escape', _('Exit Full Screen'), self.leave_fullscreen),
			('Minus', None, '', 'minus', _('Zoom Out'), self.zoom_out),
			('Plus', None, '', 'plus', _('Zoom In'), self.zoom_in),
			('Equal', None, '', 'equal', _('Zoom In'), self.zoom_in),
			('Space', None, '', 'space', _('Next Image'), self.goto_next_image),
			('Ctrl-KP_Insert', None, '', '<Ctrl>KP_Insert', _('Fit'), self.zoom_to_fit_window_action),
			('Ctrl-KP_End', None, '', '<Ctrl>KP_End', _('1:1'), self.zoom_1_to_1_action),
			('Ctrl-KP_Subtract', None, '', '<Ctrl>KP_Subtract', _('Zoom Out'), self.zoom_out),
			('Ctrl-KP_Add', None, '', '<Ctrl>KP_Add', _('Zoom In'), self.zoom_in),
			('Ctrl-KP_0', None, '', '<Ctrl>KP_0', _('Fit'), self.zoom_to_fit_window_action),
			('Ctrl-KP_1', None, '', '<Ctrl>KP_1', _('1:1'), self.zoom_1_to_1_action),
			('Full Screen Key', None, '', '<Shift>Return', None, self.enter_fullscreen),
			('Prev', None, '', 'Up', _('Previous Image'), self.goto_prev_image),
			('Next', None, '', 'Down', _('Next Image'), self.goto_next_image),
			('PgUp', None, '', 'Page_Up', _('Previous Image'), self.goto_prev_image),
			('PgDn', None, '', 'Page_Down', _('Next Image'), self.goto_next_image),
			('BackSpace', None, '', 'BackSpace', _('Previous Image'), self.goto_prev_image),
			('Prev Subfolder 2', None, '', '<Shift>Up', _('Previous Subfolder'), self.goto_first_image_prev_subfolder),
			('Next Subfolder 2', None, '', '<Shift>Down', _('Next Subfolder'), self.goto_first_image_next_subfolder),
			('Prev Subfolder 3', None, '', '<Shift>Page_Up', _('Previous Subfolder'), self.goto_first_image_prev_subfolder),
			('Next Subfolder 3', None, '', '<Shift>Page_Down', _('Next Subfolder'), self.goto_first_image_next_subfolder),
			('OriginalSize', None, '', '1', _('1:1'), self.zoom_1_to_1_action),
			('ZoomIn', None, '', 'KP_Add', _('Zoom In'), self.zoom_in),
			('ZoomOut', None, '', 'KP_Subtract', _('Zoom Out'), self.zoom_out)
			)
		toggle_actions = (
			('Status Bar', None, _('_Status Bar'), None, _('Status Bar'), self.toggle_status_bar, self.usettings['statusbar_show']),
			('Toolbar', None, _('_Toolbar'), None, _('Toolbar'), self.toggle_toolbar, self.usettings['toolbar_show']),
			('Thumbnails Pane', None, _('Thumbnails _Pane'), 'F9', _('Thumbnails Pane'), self.toggle_thumbpane, self.usettings['thumbpane_show']),
			('Randomize list', None, _('_Randomize list'), None, _('Randomize list'), self.shall_we_randomize, self.going_random),
			)

		# Populate keys[]:
		self.keys=[]
		for i in range(len(actions)):
			if len(actions[i]) > 3:
				if actions[i][3] != None:
					self.keys.append([actions[i][4], actions[i][3]])

		uiDescription = """
			<ui>
				<popup name="Popup">
				<menuitem action="Next Image"/>
				<menuitem action="Previous Image"/>
				<separator name="FM1"/>
				<menuitem action="Out"/>
				<menuitem action="In"/>
				<menuitem action="1:1"/>
				<menuitem action="Fit"/>
				<separator name="FM4"/>
				<menuitem action="Start Slideshow"/>
				<menuitem action="Stop Slideshow"/>
				<separator name="FM3"/>
				<menuitem action="Exit Full Screen"/>
				<menuitem action="Full Screen"/>
				</popup>
				<menubar name="MainMenu">
					<menu action="FileMenu">
						<menuitem action="Open Image"/>
						<menuitem action="Open Folder"/>
						<menuitem action="Open Remote Image"/>
						<menuitem action="Reload"/>
						<separator name="FM1"/>
						<menuitem action="Save"/>
						<menuitem action="Save As"/>
						<separator name="FM2"/>
						<menuitem action="Take Screenshot"/>
						<separator name="FM3"/>
						<menuitem action="Properties"/>
						<separator name="FM4"/>
						<placeholder name="Recent Files">
						</placeholder>
						<separator name="FM5"/>
						<menuitem action="Quit"/>
					</menu>
					<menu action="EditMenu">
						<menuitem action="Rotate Left"/>
						<menuitem action="Rotate Right"/>
						<menuitem action="Flip Vertically"/>
						<menuitem action="Flip Horizontally"/>
						<separator name="FM1"/>
						<menuitem action="Copy"/>
						<menuitem action="Crop"/>
						<menuitem action="Resize"/>
						<menuitem action="Saturation"/>
						<separator name="FM2"/>
						<menuitem action="Rename Image"/>
						<menuitem action="Delete Image"/>
						<separator name="FM3"/>
						<menu action="ActionSubMenu">
							<separator name="FM4" position="bot"/>
							<menuitem action="Custom Actions" position="bot"/>
						</menu>
						<menuitem action="Preferences"/>
					</menu>
					<menu action="ViewMenu">
						<menuitem action="Out"/>
						<menuitem action="In"/>
						<menuitem action="1:1"/>
						<menuitem action="Fit"/>
						<separator name="FM2"/>
						<menuitem action="Toolbar"/>
						<menuitem action="Thumbnails Pane"/>
						<menuitem action="Status Bar"/>
						<separator name="FM1"/>
						<menuitem action="Full Screen"/>
					</menu>
					<menu action="GoMenu">
						<menuitem action="Next Image"/>
						<menuitem action="Previous Image"/>
						<menuitem action="Random Image"/>
						<menuitem action="Randomize list"/>
						<separator name="FM1"/>
						<menuitem action="First Image"/>
						<menuitem action="Last Image"/>
						<separator name="FM2"/>
						<menuitem action="Next Subfolder"/>
						<menuitem action="Previous Subfolder"/>
						<separator name="FM3"/>
						<menuitem action="Start Slideshow"/>
						<menuitem action="Stop Slideshow"/>
					</menu>
					<menu action="HelpMenu">
						<menuitem action="Contents"/>
						<menuitem action="About"/>
					</menu>
					<menu action="MiscKeysMenuHidden">
						<menuitem action="Minus"/>
						<menuitem action="Escape"/>
						<menuitem action="Plus"/>
						<menuitem action="Equal"/>
						<menuitem action="Space"/>
						<menuitem action="Ctrl-KP_Insert"/>
						<menuitem action="Ctrl-KP_End"/>
						<menuitem action="Ctrl-KP_Subtract"/>
						<menuitem action="Ctrl-KP_Add"/>
						<menuitem action="Ctrl-KP_0"/>
						<menuitem action="Ctrl-KP_1"/>
						<menuitem action="Full Screen Key"/>
						<menuitem action="Prev"/>
						<menuitem action="Next"/>
						<menuitem action="PgUp"/>
						<menuitem action="PgDn"/>
						<menuitem action="Prev Subfolder 2"/>
						<menuitem action="Next Subfolder 2"/>
						<menuitem action="Prev Subfolder 3"/>
						<menuitem action="Next Subfolder 3"/>
						<menuitem action="OriginalSize"/>
						<menuitem action="BackSpace"/>
						<menuitem action="ZoomIn"/>
						<menuitem action="ZoomOut"/>
					</menu>
				</menubar>
				<toolbar name="MainToolbar">
					<toolitem action="Open Image"/>
					<separator name="FM1"/>
					<toolitem action="Previous2"/>
					<toolitem action="Next2"/>
					<separator name="FM2"/>
					<toolitem action="Out"/>
					<toolitem action="In"/>
					<toolitem action="1:1"/>
					<toolitem action="Fit"/>
				</toolbar>
			</ui>
			"""

		# Create interface
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.update_title()
		try:
			gtk.window_set_default_icon_from_file(self.find_path('mirage.png'))
		except:
			pass
		vbox = gtk.VBox(False, 0)
		self.UIManager = gtk.UIManager()
		actionGroup = gtk.ActionGroup('Actions')
		actionGroup.add_actions(actions)
		actionGroup.add_toggle_actions(toggle_actions)
		self.UIManager.insert_action_group(actionGroup, 0)
		self.UIManager.add_ui_from_string(uiDescription)
		self.refresh_custom_actions_menu()
		self.refresh_recent_files_menu()
		self.window.add_accel_group(self.UIManager.get_accel_group())
		self.menubar = self.UIManager.get_widget('/MainMenu')
		vbox.pack_start(self.menubar, False, False, 0)
		self.toolbar = self.UIManager.get_widget('/MainToolbar')
		vbox.pack_start(self.toolbar, False, False, 0)
		self.layout = gtk.Layout()
		self.vscroll = gtk.VScrollbar(None)
		self.vscroll.set_adjustment(self.layout.get_vadjustment())
		self.hscroll = gtk.HScrollbar(None)
		self.hscroll.set_adjustment(self.layout.get_hadjustment())
		self.table = gtk.Table(3, 2, False)

		self.thumblist = gtk.ListStore(gtk.gdk.Pixbuf)
		self.thumbpane = gtk.TreeView(self.thumblist)
		self.thumbcolumn = gtk.TreeViewColumn(None)
		self.thumbcell = gtk.CellRendererPixbuf()
		self.thumbcolumn.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
		self.thumbpane_set_size()
		self.thumbpane.append_column(self.thumbcolumn)
		self.thumbcolumn.pack_start(self.thumbcell, True)
		self.thumbcolumn.set_attributes(self.thumbcell, pixbuf=0)
		self.thumbpane.get_selection().set_mode(gtk.SELECTION_SINGLE)
		self.thumbpane.set_headers_visible(False)
		self.thumbpane.set_property('can-focus', False)
		self.thumbscroll = gtk.ScrolledWindow()
		self.thumbscroll.set_policy(gtk.POLICY_NEVER, gtk.POLICY_ALWAYS)
		self.thumbscroll.add(self.thumbpane)

		self.table.attach(self.thumbscroll, 0, 1, 0, 1, 0, gtk.FILL|gtk.EXPAND, 0, 0)
		self.table.attach(self.layout, 1, 2, 0, 1, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		self.table.attach(self.hscroll, 1, 2, 1, 2, gtk.FILL|gtk.SHRINK, gtk.FILL|gtk.SHRINK, 0, 0)
		self.table.attach(self.vscroll, 2, 3, 0, 1, gtk.FILL|gtk.SHRINK, gtk.FILL|gtk.SHRINK, 0, 0)
		vbox.pack_start(self.table, True, True, 0)
		
		if self.usettings['simple_bgcolor']:
			self.layout.modify_bg(gtk.STATE_NORMAL, None)
		else:
			self.layout.modify_bg(gtk.STATE_NORMAL, self.bgcolor)
		self.imageview = gtk.Image()
		self.layout.add(self.imageview)

		self.statusbar = gtk.Statusbar()
		self.statusbar2 = gtk.Statusbar()
		self.statusbar.set_has_resize_grip(False)
		self.statusbar2.set_has_resize_grip(True)
		self.statusbar2.set_size_request(200, -1)
		hbox_statusbar = gtk.HBox()
		hbox_statusbar.pack_start(self.statusbar, expand=True)
		hbox_statusbar.pack_start(self.statusbar2, expand=False)
		vbox.pack_start(hbox_statusbar, False, False, 0)
		self.window.add(vbox)
		self.window.set_property('allow-shrink', False)
		self.window.set_default_size(self.usettings['window_width'],self.usettings['window_height'])
		
		# Create slideshow window:
		self.slideshow_setup()

		# Connect signals
		self.window.connect("delete_event", self.delete_event)
		self.window.connect("destroy", self.destroy)
		self.window.connect("size-allocate", self.window_resized)
		self.window.connect("configure_event", self.store_window_size)
		self.window.connect('key-press-event', self.topwindow_keypress)
		self.toolbar.connect('focus', self.toolbar_focused)
		self.layout.drag_dest_set(gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP, [("text/uri-list", 0, 80)], gtk.gdk.ACTION_DEFAULT)
		self.layout.connect('drag_motion', self.motion_cb)
		self.layout.connect('drag_data_received', self.drop_cb)
		self.layout.add_events(gtk.gdk.KEY_PRESS_MASK | gtk.gdk.POINTER_MOTION_MASK | gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_MOTION_MASK | gtk.gdk.SCROLL_MASK)
		self.layout.connect("scroll-event", self.mousewheel_scrolled)
		self.layout.add_events(gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.KEY_PRESS_MASK)
		self.layout.connect("button_press_event", self.button_pressed)
		self.layout.add_events(gtk.gdk.POINTER_MOTION_MASK | gtk.gdk.POINTER_MOTION_HINT_MASK | gtk.gdk.BUTTON_RELEASE_MASK)
		self.layout.connect("motion-notify-event", self.mouse_moved)
		self.layout.connect("button-release-event", self.button_released)
		self.imageview.connect("expose-event", self.expose_event)
		self.thumb_sel_handler = self.thumbpane.get_selection().connect('changed', self.thumbpane_selection_changed)
		self.thumb_scroll_handler = self.thumbscroll.get_vscrollbar().connect("value-changed", self.thumbpane_scrolled)

		# Since GNOME does its own thing for the toolbar style...
		# Requires gnome-python installed to work (but optional)
		try:
			client = gconf.client_get_default()
			style = client.get_string('/desktop/gnome/interface/toolbar_style')
			if style == "both":
				self.toolbar.set_style(gtk.TOOLBAR_BOTH)
			elif style == "both-horiz":
				self.toolbar.set_style(gtk.TOOLBAR_BOTH_HORIZ)
			elif style == "icons":
				self.toolbar.set_style(gtk.TOOLBAR_ICONS)
			elif style == "text":
				self.toolbar.set_style(gtk.TOOLBAR_TEXT)
			client.add_dir("/desktop/gnome/interface", gconf.CLIENT_PRELOAD_NONE)
			client.notify_add("/desktop/gnome/interface/toolbar_style", self.gconf_key_changed)
		except:
			pass

		# Show GUI:
		if not self.usettings['toolbar_show']:
			self.toolbar.set_property('visible', False)
			self.toolbar.set_no_show_all(True)
		if not self.usettings['statusbar_show']:
			self.statusbar.set_property('visible', False)
			self.statusbar.set_no_show_all(True)
			self.statusbar2.set_property('visible', False)
			self.statusbar2.set_no_show_all(True)
		if not self.usettings['thumbpane_show']:
			self.thumbscroll.set_property('visible', False)
			self.thumbscroll.set_no_show_all(True)
		self.hscroll.set_no_show_all(True)
		self.vscroll.set_no_show_all(True)
		if ((go_into_fullscreen or self.usettings['start_in_fullscreen'])
			or (start_slideshow and self.usettings['slideshow_in_fullscreen']) and args != []):
			self.enter_fullscreen(None)
			self.statusbar.set_no_show_all(True)
			self.statusbar2.set_no_show_all(True)
			self.toolbar.set_no_show_all(True)
			self.menubar.set_no_show_all(True)
			self.thumbscroll.set_no_show_all(True)
		self.window.show_all()
		#self.ss_exit.set_size_request(self.ss_start.size_request()[0]*2, self.ss_start.size_request()[1]*2)
		#self.ss_randomize.set_size_request(self.ss_start.size_request()[0]*2, -1)
		self.ss_start.set_size_request(self.ss_start.size_request()[0]*2, -1)
		self.ss_stop.set_size_request(self.ss_stop.size_request()[0]*2, -1)
		self.UIManager.get_widget('/Popup/Exit Full Screen').hide()
		self.layout.set_flags(gtk.CAN_FOCUS)
		self.window.set_focus(self.layout)

		#sets the visibility of some menu entries
		self.set_slideshow_sensitivities()
		self.UIManager.get_widget('/MainMenu/MiscKeysMenuHidden').set_property('visible', False)

		if go_into_fullscreen:
			self.UIManager.get_widget('/Popup/Exit Full Screen').show()

		# If arguments (filenames) were passed, try to open them:
		self.image_list = []
		if args != []:
			for i in range(len(args)):
				args[i] = urllib.url2pathname(args[i]).decode('utf-8')
			gtk.gdk.threads_enter()
			self.expand_filelist_and_load_image(args)
			gtk.gdk.threads_leave()
		else:
			self.set_go_sensitivities(False)
			self.set_image_sensitivities(False)

		if start_slideshow:
			self.toggle_slideshow(None)

	def read_config_and_set_settings(self):
		config = os.path.join(self.config_dir, 'mirage1.conf')
		if os.path.isfile(config):
			# Add each entry one by one in case of missing entries in the config
			cf = open(config)
			confdict = json.load(cf)
			for k,v in confdict.items():
				self.usettings[k] = v
			# Additional work needed
			cf.close()
		# Read accel_map file, if it exists
		accel = os.path.join(self.config_dir, 'accel_map')
		if os.path.isfile(accel):
			gtk.accel_map_load(accel)

	def slideshow_setup(self):
		# Create the left-side controls
		self.slideshow_window = gtk.Window(gtk.WINDOW_POPUP)
		self.slideshow_controls = gtk.HBox()
		# Back button
		self.ss_back = gtk.Button()
		self.ss_back.add(gtk.image_new_from_stock(gtk.STOCK_GO_BACK, gtk.ICON_SIZE_BUTTON))
		self.ss_back.set_property('can-focus', False)
		self.ss_back.connect('clicked', self.goto_prev_image)
		# Start/Stop buttons
		self.ss_start = gtk.Button()
		self.ss_start.add(gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_BUTTON))
		self.ss_start.set_property('can-focus', False)
		self.ss_start.connect('clicked', self.toggle_slideshow)
		self.ss_stop = gtk.Button()
		self.ss_stop.add(gtk.image_new_from_stock(gtk.STOCK_MEDIA_STOP, gtk.ICON_SIZE_BUTTON))
		self.ss_stop.set_property('can-focus', False)
		self.ss_stop.connect('clicked', self.toggle_slideshow)
		# Forward button
		self.ss_forward = gtk.Button()
		self.ss_forward.add(gtk.image_new_from_stock(gtk.STOCK_GO_FORWARD, gtk.ICON_SIZE_BUTTON))
		self.ss_forward.set_property('can-focus', False)
		self.ss_forward.connect('clicked', self.goto_next_image)
		# Pack controls into the slideshow window
		self.slideshow_controls.pack_start(self.ss_back, False, False, 0)
		self.slideshow_controls.pack_start(self.ss_start, False, False, 0)
		self.slideshow_controls.pack_start(self.ss_stop, False, False, 0)
		self.slideshow_controls.pack_start(self.ss_forward, False, False, 0)
		self.slideshow_window.add(self.slideshow_controls)
		if self.usettings['simple_bgcolor']:
			self.slideshow_window.modify_bg(gtk.STATE_NORMAL, None)
		else:
			self.slideshow_window.modify_bg(gtk.STATE_NORMAL, self.bgcolor)
		
		# Create the right-side controls
		self.slideshow_window2 = gtk.Window(gtk.WINDOW_POPUP)
		self.slideshow_controls2 = gtk.HBox()
		try:
			self.ss_exit = gtk.Button()
			self.ss_exit.add(gtk.image_new_from_stock(gtk.STOCK_LEAVE_FULLSCREEN, gtk.ICON_SIZE_BUTTON))
		except:
			self.ss_exit = gtk.Button()
			self.ss_exit.set_image(gtk.image_new_from_stock('leave-fullscreen', gtk.ICON_SIZE_BUTTON))
		self.ss_exit.set_property('can-focus', False)
		self.ss_exit.connect('clicked', self.leave_fullscreen)
		self.ss_randomize = gtk.ToggleButton()
		try:
			pixbuf = gtk.gdk.pixbuf_new_from_file(self.find_path('stock_shuffle.png'))
			self.iconfactory.add('stock-shuffle', gtk.IconSet(pixbuf))
			self.ss_randomize.set_image(gtk.image_new_from_stock('stock-shuffle', gtk.ICON_SIZE_BUTTON))
		except:
			self.ss_randomize.set_label("Rand")
		self.ss_randomize.connect('toggled', self.random_changed)

		spin_adj = gtk.Adjustment(self.usettings['slideshow_delay'], 0, 50000, 1,100, 0)
		self.ss_delayspin = gtk.SpinButton(spin_adj, 1.0, 0)
		self.ss_delayspin.set_numeric(True)
		self.ss_delayspin.connect('changed', self.delay_changed)
		self.slideshow_controls2.pack_start(self.ss_randomize, False, False, 0)
		self.slideshow_controls2.pack_start(self.ss_delayspin, False, False, 0)
		self.slideshow_controls2.pack_start(self.ss_exit, False, False, 0)
		self.slideshow_window2.add(self.slideshow_controls2)
		if self.usettings['simple_bgcolor']:
			self.slideshow_window2.modify_bg(gtk.STATE_NORMAL, None)
		else:
			self.slideshow_window2.modify_bg(gtk.STATE_NORMAL, self.bgcolor)

	def refresh_recent_files_menu(self):
		if self.merge_id_recent:
			self.UIManager.remove_ui(self.merge_id_recent)
		if self.actionGroupRecent:
			self.UIManager.remove_action_group(self.actionGroupRecent)
			self.actionGroupRecent = None
		self.actionGroupRecent = gtk.ActionGroup('RecentFiles')
		self.UIManager.ensure_update()
		for i, file_path in enumerate(self.usettings['recentfiles']):
			if file_path:
				filename = os.path.basename(file_path)
				if filename:
					base, ext = os.path.splitext(filename)
					if len(base) > 27:
						# Replace end of file name (excluding extension) with ..
						try:
							menu_name = base[:25] + '..' + ext
						except:
							menu_name = filename
					else:
						menu_name = filename
					menu_name = menu_name.replace('_','__')
					action_id = str(i)
					action = [(action_id, None, menu_name, '<Alt>' + str(i+1), None, self.recent_action_click)]
					self.actionGroupRecent.add_actions(action)
		uiDescription = """
			<ui>
				<menubar name="MainMenu">
				<menu action="FileMenu">
					<placeholder name="Recent Files">
			"""
		for i, file_path in enumerate(self.usettings['recentfiles']):
			if file_path:
				action_id = str(i)
				uiDescription = uiDescription + """<menuitem action=\"""" + action_id + """\"/>"""
		uiDescription = uiDescription + """</placeholder></menu></menubar></ui>"""
		self.merge_id_recent = self.UIManager.add_ui_from_string(uiDescription)
		self.UIManager.insert_action_group(self.actionGroupRecent, 0)
		self.UIManager.get_widget('/MainMenu/MiscKeysMenuHidden').set_property('visible', False)

	def refresh_custom_actions_menu(self):
		if self.merge_id:
			self.UIManager.remove_ui(self.merge_id)
		if self.actionGroupCustom:
			self.UIManager.remove_action_group(self.actionGroupCustom)
			self.actionGroupCustom = None
		self.actionGroupCustom = gtk.ActionGroup('CustomActions')
		self.UIManager.ensure_update()
		for i in range(len(self.usettings['action_names'])):
			action = [(self.usettings['action_names'][i], None, self.usettings['action_names'][i], self.usettings['action_shortcuts'][i], None, self.custom_action_click)]
			self.actionGroupCustom.add_actions(action)
		uiDescription = """
			<ui>
				<menubar name="MainMenu">
					<menu action="EditMenu">
					<menu action="ActionSubMenu">
			"""
		for i in range(len(self.usettings['action_names'])):
			uiDescription = uiDescription + """<menuitem action=\"""" + self.usettings['action_names'][len(self.usettings['action_names'])-i-1].replace('&','&amp;') + """\" position="top"/>"""
		uiDescription = uiDescription + """</menu></menu></menubar></ui>"""
		self.merge_id = self.UIManager.add_ui_from_string(uiDescription)
		self.UIManager.insert_action_group(self.actionGroupCustom, 0)
		self.UIManager.get_widget('/MainMenu/MiscKeysMenuHidden').set_property('visible', False)

	def thumbpane_update_images(self, clear_first=False, force_upto_imgnum=-1):
		self.stop_now = False
		# When first populating the thumbpane, make sure we go up to at least
		# force_upto_imgnum so that we can show this image selected:
		if clear_first:
			self.thumbpane_clear_list()
		# Load all images up to the bottom ofo the visible thumbpane rect:
		rect = self.thumbpane.get_visible_rect()
		bottom_coord = rect.y + rect.height + self.usettings['thumbnail_size']
		if bottom_coord > self.thumbpane_bottom_coord_loaded:
			self.thumbpane_bottom_coord_loaded = bottom_coord
		# update images:
		if not self.thumbpane_updating:
			thread = threading.Thread(target=self.thumbpane_update_pending_images, args=(force_upto_imgnum, None))
			thread.setDaemon(True)
			thread.start()

	def thumbpane_create_dir(self):
		if not os.path.exists(os.path.expanduser('~/.thumbnails/')):
			os.mkdir(os.path.expanduser('~/.thumbnails/'))
		if not os.path.exists(os.path.expanduser('~/.thumbnails/normal/')):
			os.mkdir(os.path.expanduser('~/.thumbnails/normal/'))

	def thumbpane_update_pending_images(self, force_upto_imgnum, foo):
		self.thumbpane_updating = True
		self.thumbpane_create_dir()
		# Check to see if any images need their thumbnails generated.
		curr_coord = 0
		imgnum = 0
		while curr_coord < self.thumbpane_bottom_coord_loaded or imgnum <= force_upto_imgnum:
			if self.closing_app or self.stop_now or not self.usettings['thumbpane_show']:
				break
			if imgnum >= len(self.image_list):
				break
			self.thumbpane_set_image(self.image_list[imgnum], imgnum)
			curr_coord += self.thumbpane.get_background_area((imgnum,),self.thumbcolumn).height
			if force_upto_imgnum == imgnum:
				# Verify that the user hasn't switched images while we're loading thumbnails:
				if force_upto_imgnum == self.curr_img_in_list:
					gobject.idle_add(self.thumbpane_select, force_upto_imgnum)
			imgnum += 1
		self.thumbpane_updating = False

	def thumbpane_clear_list(self):
		self.thumbpane_bottom_coord_loaded = 0
		self.thumbscroll.get_vscrollbar().handler_block(self.thumb_scroll_handler)
		self.thumblist.clear()
		self.thumbscroll.get_vscrollbar().handler_unblock(self.thumb_scroll_handler)
		for image in self.image_list:
			blank_pix = self.get_blank_pix_for_image(image)
			self.thumblist.append([blank_pix])
		self.thumbnail_loaded = [False]*len(self.image_list)

	def thumbpane_set_image(self, image_name, imgnum, force_update=False):
		if self.usettings['thumbpane_show']:
			if not self.thumbnail_loaded[imgnum] or force_update:
				filename, thumbfile = self.thumbnail_get_name(image_name)
				pix = self.thumbpane_get_pixbuf(thumbfile, filename, force_update)
				if pix:
					if self.usettings['thumbnail_size'] != 128:
						# 128 is the size of the saved thumbnail, so convert if different:
						pix, image_width, image_height = self.get_pixbuf_of_size(pix, self.usettings['thumbnail_size'], gtk.gdk.INTERP_TILES)
					self.thumbnail_loaded[imgnum] = True
					self.thumbscroll.get_vscrollbar().handler_block(self.thumb_scroll_handler)
					pix = self.pixbuf_add_border(pix)
					try:
						self.thumblist[imgnum] = [pix]
					except:
						pass
					self.thumbscroll.get_vscrollbar().handler_unblock(self.thumb_scroll_handler)

	def thumbnail_get_name(self, image_name):
		filename = os.path.expanduser('file://' + image_name)
		uriname = os.path.expanduser('file://' + urllib.pathname2url(image_name.encode('utf-8')))
		if HAS_HASHLIB:
			m = hashlib.md5()
		else:
			m = md5.new()
		m.update(uriname)
		mhex = m.hexdigest()
		mhex_filename = os.path.expanduser('~/.thumbnails/normal/' + mhex + '.png')
		return filename, mhex_filename

	def thumbpane_get_pixbuf(self, thumb_url, image_url, force_generation):
		# Returns a valid pixbuf or None if a pixbuf cannot be generated. Tries to re-use
		# a thumbnail from ~/.thumbails/normal/, otherwise generates one with the
		# XDG filename: md5(file:///full/path/to/image).png
		imgfile = image_url
		if imgfile[:7] == 'file://':
			imgfile = imgfile[7:]
		try:
			if os.path.exists(thumb_url) and not force_generation:
				pix = gtk.gdk.pixbuf_new_from_file(thumb_url)
				pix_mtime = pix.get_option('tEXt::Thumb::MTime')
				if pix_mtime:
					st = os.stat(imgfile)
					file_mtime = str(st[stat.ST_MTIME])
					# If the mtimes match, we're good. if not, regenerate the thumbnail..
					if pix_mtime == file_mtime:
						return pix
			# Create the 128x128 thumbnail:
			uri = 'file://' + urllib.pathname2url(imgfile.encode('utf-8'))
			#pix = gtk.gdk.pixbuf_new_from_file(imgfile)
			pix = ImageData()
			pix.load_pixbuf(imgfile)
			pix, image_width, image_height = self.get_pixbuf_of_size(pix.pixbuf, 128, gtk.gdk.INTERP_TILES)
			st = os.stat(imgfile)
			file_mtime = str(st[stat.ST_MTIME])
			# Save image to .thumbnails:
			pix.save(thumb_url, "png", {'tEXt::Thumb::URI':uri, 'tEXt::Thumb::MTime':file_mtime, 'tEXt::Software':'Mirage' + __version__})
			return pix
		except:
			
			return None

	def thumbpane_load_image(self, treeview, imgnum):
		if imgnum != self.curr_img_in_list:
			gobject.idle_add(self.goto_image, str(imgnum), None)

	def thumbpane_selection_changed(self, treeview):
		cancel = self.autosave_image()
		if cancel:
			# Revert selection...
			gobject.idle_add(self.thumbpane_select, self.curr_img_in_list)
			return True
		try:
			model, paths = self.thumbpane.get_selection().get_selected_rows()
			imgnum = paths[0][0]
			if not self.thumbnail_loaded[imgnum]:
				self.thumbpane_set_image(self.image_list[imgnum], imgnum)
			gobject.idle_add(self.thumbpane_load_image, treeview, imgnum)
		except:
			pass

	def thumbpane_select(self, imgnum):
		if self.usettings['thumbpane_show']:
			self.thumbpane.get_selection().handler_block(self.thumb_sel_handler)
			try:
				self.thumbpane.get_selection().select_path((imgnum,))
				self.thumbpane.scroll_to_cell((imgnum,))
			except:
				pass
			self.thumbpane.get_selection().handler_unblock(self.thumb_sel_handler)

	def thumbpane_set_size(self):
		self.thumbcolumn.set_fixed_width(self.thumbpane_get_size())
		self.window_resized(None, self.window.allocation, True)

	def thumbpane_get_size(self):
		return int(self.usettings['thumbnail_size'] * 1.3)

	def thumbpane_scrolled(self, range):
		self.thumbpane_update_images()

	def get_blank_pix_for_image(self, image):
		# Sizes the "blank image" icon for the thumbpane. This will ensure that we don't
		# load a humongous icon for a small pix, for example, and will keep the thumbnails
		# from shifting around when they are actually loaded.
		try:
			info = gtk.gdk.pixbuf_get_file_info(image)
			imgwidth = float(info[1])
			imgheight = float(info[2])
			if imgheight > self.usettings['thumbnail_size']:
				if imgheight > imgwidth:
					imgheight = self.usettings['thumbnail_size']
				else:
					imgheight = imgheight/imgwidth * self.usettings['thumbnail_size']
			imgheight = 2 + int(imgheight) # Account for border that will be added to thumbnails..
			imgwidth = self.usettings['thumbnail_size']
		except:
			imgheight = 2 + self.usettings['thumbnail_size']
			imgwidth = self.usettings['thumbnail_size']
		blank_pix = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, imgwidth, imgheight)
		blank_pix.fill(0x00000000)
		imgwidth2 = int(imgheight*0.8)
		imgheight2 = int(imgheight*0.8)
		composite_pix = self.blank_image.scale_simple(imgwidth2, imgheight2, gtk.gdk.INTERP_BILINEAR)
		leftcoord = int((imgwidth - imgwidth2)/2)
		topcoord = int((imgheight - imgheight2)/2)
		composite_pix.copy_area(0, 0, imgwidth2, imgheight2, blank_pix, leftcoord, topcoord)
		return blank_pix

	def find_path(self, filename, exit_on_fail=True):
		""" Find a pixmap or icon by looking through standard dirs.
			If the image isn't found exit with error status 1 unless
			exit_on_fail is set to False, then return None """
		if not self.resource_path_list:
			#If executed from mirage in bin this points to the basedir
			basedir_mirage = os.path.split(sys.path[0])[0]
			#If executed from mirage.py module in python lib this points to the basedir
			f0 = os.path.split(__file__)[0].split('/lib')[0]
			self.resource_path_list = list(set(filter(os.path.isdir, [
				os.path.join(basedir_mirage, 'share', 'mirage'),
				os.path.join(basedir_mirage, 'share', 'pixmaps'),
				os.path.join(sys.prefix, 'share', 'mirage'),
				os.path.join(sys.prefix, 'share', 'pixmaps'),
				os.path.join(sys.prefix, 'local', 'share', 'mirage'),
				os.path.join(sys.prefix, 'local', 'share', 'pixmaps'),
				sys.path[0], #If it's run non-installed
				os.path.join(f0, 'share', 'mirage'),
				os.path.join(f0, 'share', 'pixmaps'),
				])))
		for path in self.resource_path_list:
			pix = os.path.join(path, filename)
			if os.path.exists(pix):
				return pix
		# If we reached here, we didn't find the pixmap
		if exit_on_fail:
			print _("Couldn't find the image %s. Please check your installation.") % filename
			gtk.main_quit(1)
		else:
			return None

	def gconf_key_changed(self, client, cnxn_id, entry, label):
		if entry.value.type == gconf.VALUE_STRING:
			style = entry.value.to_string()
			if style == "both":
				self.toolbar.set_style(gtk.TOOLBAR_BOTH)
			elif style == "both-horiz":
				self.toolbar.set_style(gtk.TOOLBAR_BOTH_HORIZ)
			elif style == "icons":
				self.toolbar.set_style(gtk.TOOLBAR_ICONS)
			elif style == "text":
				self.toolbar.set_style(gtk.TOOLBAR_TEXT)
			self.image_zoom_fit_update()

	def toolbar_focused(self, widget, direction):
		self.layout.grab_focus()
		return True

	def topwindow_keypress(self, widget, event):
		# For whatever reason, 'Left' and 'Right' cannot be used as menu
		# accelerators so we will manually check for them here:
		if (not (event.state & gtk.gdk.SHIFT_MASK)) and not (event.state & gtk.gdk.CONTROL_MASK) and not (event.state & gtk.gdk.MOD1_MASK):
			if event.keyval == gtk.gdk.keyval_from_name('Left') or event.keyval == gtk.gdk.keyval_from_name('Up'):
				self.goto_prev_image(None)
				return
			elif event.keyval == gtk.gdk.keyval_from_name('Right') or event.keyval == gtk.gdk.keyval_from_name('Down'):
				self.goto_next_image(None)
				return
		shortcut = gtk.accelerator_name(event.keyval, event.state)
		if "Escape" in shortcut:
			self.stop_now = True
			self.searching_for_images = False
			while gtk.events_pending():
				gtk.main_iteration()
			self.update_title()
			return

	def parse_action_command(self, command, batchmode):
		self.running_custom_actions = True
		self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		while gtk.events_pending():
			gtk.main_iteration()
		self.curr_custom_action = 0
		if batchmode:
			self.num_custom_actions = len(self.image_list)
			for i in range(self.num_custom_actions):
				self.curr_custom_action += 1
				self.update_statusbar()
				while gtk.events_pending():
					gtk.main_iteration()
				imagename = self.image_list[i]
				self.parse_action_command2(command, imagename)
		else:
			self.num_custom_actions = 1
			self.curr_custom_action = 1
			self.update_statusbar()
			while gtk.events_pending():
				gtk.main_iteration()
			self.parse_action_command2(command, self.currimg.name)
		gc.collect()
		self.change_cursor(None)
		# Refresh the current image or any preloaded needed if they have changed:
		if not os.path.exists(self.currimg.name):
			self.currimg.unload_pixbuf()
			self.image_load_failed(False)
		else:
			animtest = gtk.gdk.PixbufAnimation(self.currimg.name)
			if animtest.is_static_image():
				if self.images_are_different(animtest.get_static_image(), self.currimg.pixbuf_original):
					self.load_new_image2(False, False, True, False)
			else:
				if self.images_are_different(animtest, self.currimg.pixbuf_original):
					self.load_new_image2(False, False, True, False)
		self.running_custom_actions = False
		self.update_statusbar()
		while gtk.events_pending():
			gtk.main_iteration()
		if not os.path.exists(self.previmg.name):
			self.previmg.unload_pixbuf()
		else:
			animtest = gtk.gdk.PixbufAnimation(self.previmg.name)
			if animtest.is_static_image():
				if self.images_are_different(animtest.get_static_image(), self.previmg.pixbuf_original):
					self.previmg.unload_pixbuf()
					self.preload_when_idle = gobject.idle_add(self.preload_prev_image, False)
			else:
				if self.images_are_different(animtest, self.previmg.pixbuf_original):
					self.previmg.unload_pixbuf()
					self.preload_when_idle = gobject.idle_add(self.preload_prev_image, False)
		if not os.path.exists(self.nextimg.name):
			self.nextimg.unload_pixbuf()
		else:
			animtest = gtk.gdk.PixbufAnimation(self.nextimg.name)
			if animtest.is_static_image():
				if self.images_are_different(animtest.get_static_image(), self.nextimg.pixbuf_original):
					self.nextimg.unload_pixbuf()
					self.preload_when_idle = gobject.idle_add(self.preload_next_image, False)
			else:
				if self.images_are_different(animtest, self.nextimg.pixbuf_original):
					self.nextimg.unload_pixbuf()
					self.preload_when_idle = gobject.idle_add(self.preload_next_image, False)
		self.stop_now = False
		if batchmode:
			# Update all thumbnails:
			gobject.idle_add(self.thumbpane_update_images, True, self.curr_img_in_list)
		else:
			# Update only the current thumbnail:
			gobject.idle_add(self.thumbpane_set_image, self.image_list[self.curr_img_in_list], self.curr_img_in_list, True)

	def images_are_different(self, pixbuf1, pixbuf2):
		if pixbuf1.get_pixels() == pixbuf2.get_pixels():
			return False
		else:
			return True

	def recent_action_click(self, action):
		self.stop_now = True
		while gtk.events_pending():
			gtk.main_iteration()
		cancel = self.autosave_image()
		if cancel:
			return
		index = int(action.get_name())
		if os.path.isfile(self.usettings['recentfiles'][index]) or os.path.exists(self.usettings['recentfiles'][index]) or self.usettings['recentfiles'][index].startswith('http://') or self.usettings['recentfiles'][index].startswith('ftp://'):
			self.expand_filelist_and_load_image([self.usettings['recentfiles'][index]])
		else:
			self.image_list = []
			self.curr_img_in_list = 0
			self.image_list.append(self.usettings['recentfiles'][index])
			self.image_load_failed(False)
			self.recent_file_remove_and_refresh(index)

	def recent_file_remove_and_refresh_name(self, rmfile):
		index_num = 0
		for imgfile in self.usettings['recentfiles']:
			if imgfile == rmfile:
				self.recent_file_remove_and_refresh(index_num)
				break
			index_num += index_num

	def recent_file_remove_and_refresh(self, index_num):
		i = index_num
		while i < len(self.usettings['recentfiles'])-1:
			self.usettings['recentfiles'][i] = self.usettings['recentfiles'][i+1]
			i = i + 1
		# Set last item empty:
		self.usettings['recentfiles'][len(self.usettings['recentfiles'])-1] = ''
		self.refresh_recent_files_menu()

	def recent_file_add_and_refresh(self, addfile):
		if not addfile:
			# Nothing to work with.
			return
		# First check if the filename is already in the list:
		if addfile in self.usettings['recentfiles']:
			self.usettings['recentfiles'].remove(addfile)
		self.usettings['recentfiles'].insert(0, addfile)
		self.refresh_recent_files_menu()

	def custom_action_click(self, action):
		if self.UIManager.get_widget('/MainMenu/EditMenu/ActionSubMenu/' + action.get_name()).get_property('sensitive'):
			for i in range(len(self.usettings['action_shortcuts'])):
				try:
					if action.get_name() == self.usettings['action_names'][i]:
						self.parse_action_command(self.usettings['action_commands'][i], self.usettings['action_batch'][i])
				except:
					pass


	def parse_action_command2(self, cmd, imagename):
		# Executes the given command using ``os.system``, substituting "%"-macros approprately.
		def sh_esc(s):
			import re
			return re.sub(r'[^/._a-zA-Z0-9-]', lambda c: '\\'+c.group(), s)
		cmd = cmd.strip()
		# [NEXT] and [PREV] are only valid alone or at the end of the command
		if cmd == "[NEXT]":
			self.goto_next_image(None)
			return
		elif cmd == "[PREV]":
			self.goto_prev_image(None)
			return
		# -1=go to previous, 1=go to next, 0=don't change
		prev_or_next=0
		if cmd[-6:] == "[NEXT]":
			prev_or_next=1
			cmd = cmd[:-6]
		elif cmd[-6:] == "[PREV]":
			prev_or_next=-1
			cmd = cmd[:-6]
		if "%F" in cmd:
			cmd = cmd.replace("%F", sh_esc(imagename))
		if "%N" in cmd:
			cmd = cmd.replace("%N", sh_esc(os.path.splitext(os.path.basename(imagename))[0]))
		if "%P" in cmd:
			cmd = cmd.replace("%P", sh_esc(os.path.dirname(imagename) + "/"))
		if "%E" in cmd:
			cmd = cmd.replace("%E", sh_esc(os.path.splitext(os.path.basename(imagename))[1]))
		if "%L" in cmd:
			cmd = cmd.replace("%L", " ".join([sh_esc(s) for s in self.image_list]))
		if self.verbose:
			print _("Action: %s") % cmd
		shell_rc = os.system(cmd) >> 8
		if self.verbose:
			print _("Action return code: %s") % shell_rc
		if shell_rc != 0:
			msg = _('Unable to launch \"%s\". Please specify a valid command from Edit > Custom Actions.') % cmd
			error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, msg)
			error_dialog.set_title(_("Invalid Custom Action"))
			error_dialog.run()
			error_dialog.destroy()
		elif prev_or_next == 1:
			self.goto_next_image(None)
		elif prev_or_next == -1:
			self.goto_prev_image(None)
		self.running_custom_actions = False

	def set_go_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/Previous Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Next Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Random Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/First Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Last Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Previous Subfolder').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Next Subfolder').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Previous Image').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Next Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/Previous2').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/Next2').set_sensitive(enable)
		self.ss_forward.set_sensitive(enable)
		self.ss_back.set_sensitive(enable)

	def set_image_sensitivities(self, enable):
		self.set_zoom_in_sensitivities(enable)
		self.set_zoom_out_sensitivities(enable)
		self.UIManager.get_widget('/MainMenu/ViewMenu/1:1').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/ViewMenu/Fit').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Delete Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Rename Image').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Copy').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Crop').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Resize').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Saturation').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/1:1').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/Fit').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/1:1').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Fit').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/FileMenu/Save As').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_sensitive(False)
		self.UIManager.get_widget('/MainMenu/FileMenu/Properties').set_sensitive(False)
		# Only jpeg, png, and bmp images are currently supported for saving
		if self.image_list:
			try:
				self.UIManager.get_widget('/MainMenu/FileMenu/Properties').set_sensitive(True)
				if self.currimg.writable_format():
					self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_sensitive(enable)
			except:
				self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_sensitive(False)
		if self.actionGroupCustom:
			for action in self.usettings['action_names']:
				self.UIManager.get_widget('/MainMenu/EditMenu/ActionSubMenu/' + action).set_sensitive(enable)
		if not HAS_IMGFUNCS:
			enable = False
		self.UIManager.get_widget('/MainMenu/EditMenu/Rotate Left').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Rotate Right').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Flip Vertically').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/EditMenu/Flip Horizontally').set_sensitive(enable)

	def set_zoom_in_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/ViewMenu/In').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/In').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/In').set_sensitive(enable)

	def set_zoom_out_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/ViewMenu/Out').set_sensitive(enable)
		self.UIManager.get_widget('/MainToolbar/Out').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Out').set_sensitive(enable)

	def set_next_image_sensitivities(self, enable):
		self.UIManager.get_widget('/MainToolbar/Next2').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Next Image').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Next Image').set_sensitive(enable)
		self.ss_forward.set_sensitive(enable)

	def set_previous_image_sensitivities(self, enable):
		self.UIManager.get_widget('/MainToolbar/Previous2').set_sensitive(enable)
		self.UIManager.get_widget('/MainMenu/GoMenu/Previous Image').set_sensitive(enable)
		self.UIManager.get_widget('/Popup/Previous Image').set_sensitive(enable)
		self.ss_back.set_sensitive(enable)

	def set_next_subfolder_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/Next Subfolder').set_sensitive(enable)

	def set_previous_subfolder_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/Previous Subfolder').set_sensitive(enable)

	def set_first_image_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/First Image').set_sensitive(enable)

	def set_last_image_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/Last Image').set_sensitive(enable)

	def set_random_image_sensitivities(self, enable):
		self.UIManager.get_widget('/MainMenu/GoMenu/Random Image').set_sensitive(enable)

	def set_slideshow_sensitivities(self):
		if len(self.image_list) <=1:
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').show()
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').set_sensitive(False)
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').hide()
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').set_sensitive(False)
		elif self.slideshow_mode:
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').hide()
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').set_sensitive(False)
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').show()
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').set_sensitive(True)
		else:
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').show()
			self.UIManager.get_widget('/MainMenu/GoMenu/Start Slideshow').set_sensitive(True)
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').hide()
			self.UIManager.get_widget('/MainMenu/GoMenu/Stop Slideshow').set_sensitive(False)
		if self.slideshow_mode:
			self.UIManager.get_widget('/Popup/Start Slideshow').hide()
			self.UIManager.get_widget('/Popup/Stop Slideshow').show()
		else:
			self.UIManager.get_widget('/Popup/Start Slideshow').show()
			self.UIManager.get_widget('/Popup/Stop Slideshow').hide()
		if len(self.image_list) <=1:
			self.UIManager.get_widget('/Popup/Start Slideshow').set_sensitive(False)
		else:
			self.UIManager.get_widget('/Popup/Start Slideshow').set_sensitive(True)

	def set_zoom_sensitivities(self):
		if not self.currimg.animation:
			self.set_zoom_out_sensitivities(True)
			self.set_zoom_in_sensitivities(True)
		else:
			self.set_zoom_out_sensitivities(False)
			self.set_zoom_in_sensitivities(False)

	def print_version(self):
		print _("Version: %s") % __appname__, __version__
		print _("Website: http://mirageiv.berlios.de")

	def print_usage(self):
		self.print_version()
		print ""
		print _("Usage: mirage [OPTION]... FILES|FOLDERS...")
		print ""
		print _("Options") + ":"
		print "  -h, --help           " + _("Show this help and exit")
		print "  -v, --version        " + _("Show version information and exit")
		print "  -V, --verbose        " + _("Show more detailed information")
		print "  -R, --recursive      " + _("Recursively include all images found in")
		print "                       " + _("subdirectories of FOLDERS")
		print "  -s, --slideshow      " + _("Start in slideshow mode")
		print "  -f, --fullscreen     " + _("Start in fullscreen mode")
		print "  -n, --no-sort        " + _("Do not sort input list")
		print "  -o, --onload 'cmd'   " + _("Execute 'cmd' when an image is loaded")
		print "                       " + _("uses same syntax as custom actions,")
		print "                       " + _("i.e. mirage -o 'echo file is %F'")

	def delay_changed(self, action):
		self.curr_slideshow_delay = self.ss_delayspin.get_value()
		if self.slideshow_mode:
			gobject.source_remove(self.timer_delay)
			if self.curr_slideshow_random:
				self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_random_image, "ss", True)
			else:
				self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_next_image, "ss", True)
		self.window.set_focus(self.layout)

	def random_changed(self, action):
		self.curr_slideshow_random = self.ss_randomize.get_active()

	def motion_cb(self, widget, context, x, y, time):
		context.drag_status(gtk.gdk.ACTION_COPY, time)
		return True

	def drop_cb(self, widget, context, x, y, selection, info, time):
		uri = selection.data.strip()
		path = urllib.url2pathname(uri.encode('utf-8'))
		paths = path.rsplit('\n')
		for i, path in enumerate(paths):
			paths[i] = path.rstrip('\r')
		self.expand_filelist_and_load_image(paths)

	def put_error_image_to_window(self):
		self.imageview.set_from_stock(gtk.STOCK_MISSING_IMAGE, gtk.ICON_SIZE_LARGE_TOOLBAR)
		self.currimg.width = self.imageview.size_request()[0]
		self.currimg.height = self.imageview.size_request()[1]
		self.center_image()
		self.set_go_sensitivities(False)
		self.set_image_sensitivities(False)
		self.update_statusbar()
		self.loaded_img_in_list = -1
		return

	def expose_event(self, widget, event):
		if self.updating_adjustments:
			return
		self.updating_adjustments = True
		if self.hscroll.get_property('visible'):
			try:
				zoomratio = float(self.currimg.width)/self.previmg_width
				newvalue = abs(self.layout.get_hadjustment().get_value() * zoomratio + (self.available_image_width()) * (zoomratio - 1) / 2)
				if newvalue >= self.layout.get_hadjustment().lower and newvalue <= (self.layout.get_hadjustment().upper - self.layout.get_hadjustment().page_size):
					self.layout.get_hadjustment().set_value(newvalue)
			except:
				pass
		if self.vscroll.get_property('visible'):
			try:
				newvalue = abs(self.layout.get_vadjustment().get_value() * zoomratio + (self.available_image_height()) * (zoomratio - 1) / 2)
				if newvalue >= self.layout.get_vadjustment().lower and newvalue <= (self.layout.get_vadjustment().upper - self.layout.get_vadjustment().page_size):
					self.layout.get_vadjustment().set_value(newvalue)
				self.previmg_width = self.currimg.width
			except:
				pass
		self.updating_adjustments = False

	def window_resized(self, widget, allocation, force_update=False):
		# Update the image size on window resize if the current image was last fit:
		if self.image_loaded:
			if force_update or allocation.width != self.prevwinwidth or allocation.height != self.prevwinheight:
				if self.last_image_action_was_fit:
					self.image_zoom_fit_update()
				else:
					self.center_image()
				self.load_new_image_stop_now()
				self.show_scrollbars_if_needed()
				# Also, regenerate preloaded image for new window size:
				self.preload_when_idle = gobject.idle_add(self.preload_next_image, True)
				self.preload_when_idle2 = gobject.idle_add(self.preload_prev_image, True)
		self.prevwinwidth = allocation.width
		self.prevwinheight = allocation.height
		return

	def save_settings(self):
		# Save the config as json
		if not os.path.exists(self.config_dir):
			os.makedirs(self.config_dir)
		conffile = os.path.join(self.config_dir, 'mirage1.conf')
		cf = open(conffile, 'w')
		json.dump(self.usettings, cf, indent=4)
		cf.close()

		# Also, save accel_map:
		gtk.accel_map_save(self.config_dir + '/accel_map')
	
	def store_window_size(self,widget,event):
		# When the window is resized, store the size in the settings
		x,y,w,h = widget.get_allocation()
		self.usettings['window_width'] = w
		self.usettings['window_height'] = h

	def delete_event(self, widget, event, data=None):
		cancel = self.autosave_image()
		if cancel:
			return True
		self.stop_now = True
		self.closing_app = True
		self.save_settings()
		gtk.main_quit(0)

	def destroy(self, event, data=None):
		cancel = self.autosave_image()
		if cancel:
			return True
		self.stop_now = True
		self.closing_app = True
		self.save_settings()

	def exit_app(self, action):
		cancel = self.autosave_image()
		if cancel:
			return True
		self.stop_now = True
		self.closing_app = True
		self.save_settings()
		gtk.main_quit(0)

	def put_zoom_image_to_window(self, currimg_preloaded, zoom_ratio=1):
		self.window.window.freeze_updates()
		if not currimg_preloaded:
			# Zoom the pixbuf
			colormap = self.imageview.get_colormap()
			self.currimg.zoom_pixbuf(zoom_ratio, self.zoom_quality, colormap)
		self.layout.set_size(self.currimg.width, self.currimg.height)
		self.center_image()
		self.show_scrollbars_if_needed()
		if not self.currimg.animation:
			self.imageview.set_from_pixbuf(self.currimg.pixbuf)
			self.previmage_is_animation = False
		else:
			self.imageview.set_from_animation(self.currimg.pixbuf)
			self.previmage_is_animation = True
		# Clean up (free memory) because I'm lazy
		gc.collect()
		self.window.window.thaw_updates()
		self.loaded_img_in_list = self.curr_img_in_list

	def show_scrollbars_if_needed(self):
		if self.currimg.width > self.available_image_width():
			self.hscroll.show()
		else:
			self.hscroll.hide()
		if self.currimg.height > self.available_image_height():
			self.vscroll.show()
		else:
			self.vscroll.hide()

	def center_image(self):
		x_shift = int((self.available_image_width() - self.currimg.width)/2)
		if x_shift < 0:
			x_shift = 0
		y_shift = int((self.available_image_height() - self.currimg.height)/2)
		if y_shift < 0:
			y_shift = 0
		self.layout.move(self.imageview, x_shift, y_shift)

	def available_image_width(self):
		width = self.window.get_size()[0]
		if not self.fullscreen_mode:
			if self.usettings['thumbpane_show']:
				width -= self.thumbscroll.size_request()[0]
		return width

	def available_image_height(self):
		height = self.window.get_size()[1]
		if not self.fullscreen_mode:
			height -= self.menubar.size_request()[1]
			if self.usettings['toolbar_show']:
				height -= self.toolbar.size_request()[1]
			if self.usettings['statusbar_show']:
				height -= self.statusbar.size_request()[1]
		return height

	def save_image(self, action):
		if self.UIManager.get_widget('/MainMenu/FileMenu/Save').get_property('sensitive'):
			self.save_image_now(self.currimg.name)

	def save_image_as(self, action):
		dialog = gtk.FileChooserDialog(title=_("Save As"),action=gtk.FILE_CHOOSER_ACTION_SAVE,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_SAVE,gtk.RESPONSE_OK))
		dialog.set_default_response(gtk.RESPONSE_OK)
		filename = os.path.basename(self.currimg.name)
		filetype = None
		dialog.set_current_folder(os.path.dirname(self.currimg.name))
		dialog.set_current_name(filename)
		dialog.set_do_overwrite_confirmation(True)
		response = dialog.run()
		if response == gtk.RESPONSE_OK:
			prev_name = self.currimg.name
			filename = dialog.get_filename()
			dialog.destroy()
			fileext = os.path.splitext(os.path.basename(filename))[1].lower()
			if len(fileext) > 0:
				fileext = fileext[1:]
			self.save_image_now(filename, fileext)
			self.register_file_with_recent_docs(filename)
		else:
			dialog.destroy()

	def save_image_now(self, dest_name, fileext=None):
		try:
			self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			while gtk.events_pending():
				gtk.main_iteration()
			if fileext == None:
				writable = self.currimg.writable_format()
				filetype = self.currimg.fileinfo['name']
			else:
				writable = False
				for i in gtk.gdk.pixbuf_get_formats():
					if fileext in i['extensions']:
						if i['is_writable']:
							writable = True
							filetype = i['name']
							break
			if writable:
				self.currimg.pixbuf_original.save(dest_name, filetype, {'quality': str(self.usettings['quality_save'])})
				self.currimg.name = dest_name
				self.image_list[self.curr_img_in_list] = dest_name
				self.update_title()
				self.update_statusbar()
				# Update thumbnail:
				gobject.idle_add(self.thumbpane_set_image, dest_name, self.curr_img_in_list, True)
				self.image_modified = False
			else:
				error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_YES_NO, _('The %s format is not supported for saving. Do you wish to save the file in a different format?') % filetype)
				error_dialog.set_title(_("Save"))
				response = error_dialog.run()
				if response == gtk.RESPONSE_YES:
					error_dialog.destroy()
					while gtk.events_pending():
						gtk.main_iteration()
					self.save_image_as(None)
				else:
					error_dialog.destroy()
		except:
			error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('Unable to save %s') % dest_name)
			error_dialog.set_title(_("Save"))
			error_dialog.run()
			error_dialog.destroy()
		self.change_cursor(None)

	def autosave_image(self):
		# Returns True if the user has canceled out of the dialog
		# Never call this function from an idle or timeout loop! That will cause
		# the app to freeze.
		if self.image_modified:
			if self.usettings['savemode'] == 1:
				temp = self.UIManager.get_widget('/MainMenu/FileMenu/Save').get_property('sensitive')
				self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_property('sensitive', True)
				self.save_image(None)
				self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_property('sensitive', temp)
			elif self.usettings['savemode'] == 2:
				dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_NONE, _("The current image has been modified. Save changes?"))
				dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
				dialog.add_button(gtk.STOCK_NO, gtk.RESPONSE_NO)
				dialog.add_button(gtk.STOCK_SAVE, gtk.RESPONSE_YES)
				dialog.set_title(_("Save?"))
				dialog.set_default_response(gtk.RESPONSE_YES)
				response = dialog.run()
				dialog.destroy()
				if response == gtk.RESPONSE_YES:
					temp = self.UIManager.get_widget('/MainMenu/FileMenu/Save').get_property('sensitive')
					self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_property('sensitive', True)
					self.save_image(None)
					self.UIManager.get_widget('/MainMenu/FileMenu/Save').set_property('sensitive', temp)
					self.image_modified = False
				elif response == gtk.RESPONSE_NO:
					self.image_modified = False
					# Ensures that we don't use the current pixbuf for any preload pixbufs if we are in
					# the process of loading the previous or next image in the list:
					self.currimg.pixbuf = self.currimg.pixbuf_original
					self.nextimg.index = -1
					self.previmg.index = -1
					self.loaded_img_in_list = -1
				else:
					return True

	def open_file_remote(self, action):
		# Prompt user for the url:
		dialog = gtk.Dialog(_("Open Remote"), self.window, gtk.DIALOG_MODAL, buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK))
		location = gtk.Entry()
		location.set_size_request(300, -1)
		location.set_activates_default(True)
		hbox = gtk.HBox()
		hbox.pack_start(gtk.Label(_("Image Location (URL):")), False, False, 5)
		hbox.pack_start(location, True, True, 5)
		dialog.vbox.pack_start(hbox, True, True, 10)
		dialog.set_default_response(gtk.RESPONSE_OK)
		dialog.vbox.show_all()
		dialog.connect('response', self.open_file_remote_response,  location)
		response = dialog.show()

	def open_file_remote_response(self, dialog, response, location):
		if response == gtk.RESPONSE_OK:
			filenames = []
			filenames.append(location.get_text())
			dialog.destroy()
			while gtk.events_pending():
				gtk.main_iteration()
			self.expand_filelist_and_load_image(filenames)
		else:
			dialog.destroy()

	def open_file(self, action):
		self.open_file_or_folder(action, True)

	def open_folder(self, action):
		self.open_file_or_folder(action, False)

	def open_file_or_folder(self, action, isfile):
		self.stop_now = True
		while gtk.events_pending():
			gtk.main_iteration()
		self.thumbpane_create_dir()
		cancel = self.autosave_image()
		if cancel:
			return
		# If isfile = True, file; If isfile = False, folder
		dialog = gtk.FileChooserDialog(title=_("Open"),action=gtk.FILE_CHOOSER_ACTION_OPEN,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK))
		if isfile:
			filter = gtk.FileFilter()
			filter.set_name(_("Images"))
			filter.add_pixbuf_formats()
			dialog.add_filter(filter)
			filter = gtk.FileFilter()
			filter.set_name(_("All files"))
			filter.add_pattern("*")
			dialog.add_filter(filter)
			preview = gtk.Image()
			dialog.set_preview_widget(preview)
			dialog.set_use_preview_label(False)
			dialog.connect("update-preview", self.update_preview, preview)
			recursivebutton = None
		else:
			dialog.set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)
			recursivebutton = gtk.CheckButton(label=_("Include images in subdirectories"))
			dialog.set_extra_widget(recursivebutton)
		dialog.set_default_response(gtk.RESPONSE_OK)
		dialog.set_select_multiple(True)
		if self.usettings['use_last_dir']:
			if self.usettings['last_dir'] != None:
				dialog.set_current_folder(self.usettings['last_dir'])
		else:
			if self.usettings['fixed_dir'] != None:
				dialog.set_current_folder(self.usettings['fixed_dir'])
		dialog.connect("response", self.open_file_or_folder_response, isfile, recursivebutton)
		response = dialog.show()

	def open_file_or_folder_response(self, dialog, response, isfile, recursivebutton):
		if response == gtk.RESPONSE_OK:
			if self.usettings['use_last_dir']:
				self.usettings['last_dir'] = dialog.get_current_folder()
			if not isfile and recursivebutton.get_property('active'):
				self.recursive = True
			filenames = dialog.get_filenames()
			dialog.destroy()
			while gtk.events_pending():
				gtk.main_iteration()
			self.expand_filelist_and_load_image(filenames)
		else:
			dialog.destroy()

	def update_preview(self, file_chooser, preview):
		filename = file_chooser.get_preview_filename()
		if not filename:
			return
		filename, thumbfile = self.thumbnail_get_name(filename)
		pixbuf = self.thumbpane_get_pixbuf(thumbfile, filename, False)
		if pixbuf:
			preview.set_from_pixbuf(pixbuf)
		else:
			pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, 1, 8, 128, 128)
			pixbuf.fill(0x00000000)
			preview.set_from_pixbuf(pixbuf)
		have_preview = True
		file_chooser.set_preview_widget_active(have_preview)
		del pixbuf
		gc.collect()

	def hide_cursor(self):
		if self.fullscreen_mode and not self.user_prompt_visible and not self.slideshow_controls_visible:
			pix_data = """/* XPM */
			static char * invisible_xpm[] = {
			"1 1 1 1",
			"       c None",
			" "};"""
			color = gtk.gdk.Color()
			pix = gtk.gdk.pixmap_create_from_data(None, pix_data, 1, 1, 1, color, color)
			invisible = gtk.gdk.Cursor(pix, pix, color, color, 0, 0)
			self.change_cursor(invisible)
		return False

	def enter_fullscreen(self, action):
		if not self.fullscreen_mode:
			self.fullscreen_mode = True
			self.UIManager.get_widget('/Popup/Full Screen').hide()
			self.UIManager.get_widget('/Popup/Exit Full Screen').show()
			self.statusbar.hide()
			self.statusbar2.hide()
			self.toolbar.hide()
			self.menubar.hide()
			self.thumbscroll.hide()
			self.thumbpane.hide()
			self.window.fullscreen()
			self.timer_id = gobject.timeout_add(2000, self.hide_cursor)
			self.set_slideshow_sensitivities()
			if self.usettings['simple_bgcolor']:
				self.layout.modify_bg(gtk.STATE_NORMAL, self.bgcolor)
		else:
			if self.usettings['simple_bgcolor']:
				self.layout.modify_bg(gtk.STATE_NORMAL, None)
			self.leave_fullscreen(action)

	def leave_fullscreen(self, action):
		if self.fullscreen_mode:
			self.slideshow_controls_visible = False
			self.slideshow_window.hide_all()
			self.slideshow_window2.hide_all()
			self.fullscreen_mode = False
			self.UIManager.get_widget('/Popup/Full Screen').show()
			self.UIManager.get_widget('/Popup/Exit Full Screen').hide()
			if self.usettings['toolbar_show']:
				self.toolbar.show()
			self.menubar.show()
			if self.usettings['statusbar_show']:
				self.statusbar.show()
				self.statusbar2.show()
			if self.usettings['thumbpane_show']:
				self.thumbscroll.show()
				self.thumbpane.show()
				self.thumbpane_update_images(False, self.curr_img_in_list)
			self.window.unfullscreen()
			self.change_cursor(None)
			self.set_slideshow_sensitivities()
			if self.usettings['simple_bgcolor']:
				self.layout.modify_bg(gtk.STATE_NORMAL, None)

	def toggle_status_bar(self, action):
		if self.statusbar.get_property('visible'):
			self.statusbar.hide()
			self.statusbar2.hide()
			self.usettings['statusbar_show'] = False
		else:
			self.statusbar.show()
			self.statusbar2.show()
			self.usettings['statusbar_show'] = True
		self.image_zoom_fit_update()

	def toggle_thumbpane(self, action):
		if self.thumbscroll.get_property('visible'):
			self.thumbscroll.hide()
			self.thumbpane.hide()
			self.usettings['thumbpane_show'] = False
		else:
			self.thumbscroll.show()
			self.thumbpane.show()
			self.usettings['thumbpane_show'] = True
			self.stop_now = False
			gobject.idle_add(self.thumbpane_update_images, True, self.curr_img_in_list)
		self.image_zoom_fit_update()

	def toggle_toolbar(self, action):
		if self.toolbar.get_property('visible'):
			self.toolbar.hide()
			self.usettings['toolbar_show'] = False
		else:
			self.toolbar.show()
			self.usettings['toolbar_show'] = True
		self.image_zoom_fit_update()

	def update_statusbar(self):
		# Update status bar:
		try:
			st = os.stat(self.currimg.name)
			filesize = st[stat.ST_SIZE]/1000
			ratio = int(100 * self.currimg.zoomratio)
			status_text = os.path.basename(self.currimg.name)+ ":  " +  str(self.currimg.pixbuf_original.get_width()) + "x" + str(self.currimg.pixbuf_original.get_height()) + "   " + str(filesize) + "KB   " + str(ratio) + "%   "
		except:
			status_text=_("Cannot load image.")
		self.statusbar.push(self.statusbar.get_context_id(""), status_text)
		status_text = ""
		if self.running_custom_actions:
			status_text = _('Custom actions: %(current)i of  %(total)i') % {'current': self.curr_custom_action,'total': self.num_custom_actions}
		elif self.searching_for_images:
			status_text = _('Scanning...')
		self.statusbar2.push(self.statusbar2.get_context_id(""), status_text)

	def show_custom_actions(self, action):
		self.actions_dialog = gtk.Dialog(title=_("Configure Custom Actions"), parent=self.window)
		self.actions_dialog.set_has_separator(False)
		self.actions_dialog.set_resizable(False)
		table_actions = gtk.Table(13, 2, False)
		table_actions.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		actionscrollwindow = gtk.ScrolledWindow()
		self.actionstore = gtk.ListStore(str, str, str)
		self.actionwidget = gtk.TreeView()
		self.actionwidget.set_enable_search(False)
		self.actionwidget.set_rules_hint(True)
		self.actionwidget.connect('row-activated', self.edit_custom_action2)
		actionscrollwindow.add(self.actionwidget)
		actionscrollwindow.set_shadow_type(gtk.SHADOW_IN)
		actionscrollwindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		actionscrollwindow.set_size_request(500, 200)
		self.actionwidget.set_model(self.actionstore)
		self.cell = gtk.CellRendererText()
		self.cellbool = gtk.CellRendererPixbuf()
		self.tvcolumn0 = gtk.TreeViewColumn(_("Batch"))
		self.tvcolumn1 = gtk.TreeViewColumn(_("Action"), self.cell, markup=0)
		self.tvcolumn2 = gtk.TreeViewColumn(_("Shortcut"))
		self.tvcolumn1.set_max_width(self.actionwidget.size_request()[0] - self.tvcolumn0.get_width() - self.tvcolumn2.get_width())
		self.actionwidget.append_column(self.tvcolumn0)
		self.actionwidget.append_column(self.tvcolumn1)
		self.actionwidget.append_column(self.tvcolumn2)
		self.populate_treeview()
		if len(self.usettings['action_names']) > 0:
			self.actionwidget.get_selection().select_path(0)
		vbox_actions = gtk.VBox()
		addbutton = gtk.Button("", gtk.STOCK_ADD)
		addbutton.get_child().get_child().get_children()[1].set_text('')
		addbutton.connect('clicked', self.add_custom_action, self.actionwidget)
		addbutton.set_tooltip_text(_("Add action"))
		editbutton = gtk.Button("", gtk.STOCK_EDIT)
		editbutton.get_child().get_child().get_children()[1].set_text('')
		editbutton.connect('clicked', self.edit_custom_action, self.actionwidget)
		editbutton.set_tooltip_text(_("Edit selected action."))
		removebutton = gtk.Button("", gtk.STOCK_REMOVE)
		removebutton.get_child().get_child().get_children()[1].set_text('')
		removebutton.connect('clicked', self.remove_custom_action)
		removebutton.set_tooltip_text(_("Remove selected action."))
		upbutton = gtk.Button("", gtk.STOCK_GO_UP)
		upbutton.get_child().get_child().get_children()[1].set_text('')
		upbutton.connect('clicked', self.custom_action_move_up, self.actionwidget)
		upbutton.set_tooltip_text(_("Move selected action up."))
		downbutton = gtk.Button("", gtk.STOCK_GO_DOWN)
		downbutton.get_child().get_child().get_children()[1].set_text('')
		downbutton.connect('clicked', self.custom_action_move_down, self.actionwidget)
		downbutton.set_tooltip_text(_("Move selected action down."))
		vbox_buttons = gtk.VBox()
		propertyinfo = gtk.Label()
		propertyinfo.set_markup('<small>' + _("Parameters") + ':\n<span font_family="Monospace">%F</span> - ' + _("File path, name, and extension") + '\n<span font_family="Monospace">%P</span> - ' + _("File path") + '\n<span font_family="Monospace">%N</span> - ' + _("File name without file extension") + '\n<span font_family="Monospace">%E</span> - ' + _("File extension (i.e. \".png\")") + '\n<span font_family="Monospace">%L</span> - ' + _("List of files, space-separated") + '</small>')
		propertyinfo.set_alignment(0, 0)
		actioninfo = gtk.Label()
		actioninfo.set_markup('<small>' + _("Operations") + ':\n<span font_family="Monospace">[NEXT]</span> - ' + _("Go to next image") + '\n<span font_family="Monospace">[PREV]</span> - ' + _("Go to previous image") +'</small>')
		actioninfo.set_alignment(0, 0)
		hbox_info = gtk.HBox()
		hbox_info.pack_start(propertyinfo, False, False, 15)
		hbox_info.pack_start(actioninfo, False, False, 15)
		vbox_buttons.pack_start(addbutton, False, False, 5)
		vbox_buttons.pack_start(editbutton, False, False, 5)
		vbox_buttons.pack_start(removebutton, False, False, 5)
		vbox_buttons.pack_start(upbutton, False, False, 5)
		vbox_buttons.pack_start(downbutton, False, False, 0)
		hbox_top = gtk.HBox()
		hbox_top.pack_start(actionscrollwindow, True, True, 5)
		hbox_top.pack_start(vbox_buttons, False, False, 5)
		vbox_actions.pack_start(hbox_top, True, True, 5)
		vbox_actions.pack_start(hbox_info, False, False, 5)
		hbox_instructions = gtk.HBox()
		info_image = gtk.Image()
		info_image.set_from_stock(gtk.STOCK_DIALOG_INFO, gtk.ICON_SIZE_BUTTON)
		hbox_instructions.pack_start(info_image, False, False, 5)
		instructions = gtk.Label(_("Here you can define custom actions with shortcuts. Actions use the built-in parameters and operations listed below and can have multiple statements separated by a semicolon. Batch actions apply to all images in the list."))
		instructions.set_line_wrap(True)
		instructions.set_alignment(0, 0.5)
		hbox_instructions.pack_start(instructions, False, False, 5)
		table_actions.attach(hbox_instructions, 1, 3, 2, 3,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 5, 0)
		table_actions.attach(gtk.Label(), 1, 3, 3, 4,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_actions.attach(vbox_actions, 1, 3, 4, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_actions.attach(gtk.Label(), 1, 3, 12, 13,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		self.actions_dialog.vbox.pack_start(table_actions, False, False, 0)
		# Show dialog:
		self.actions_dialog.vbox.show_all()
		instructions.set_size_request(self.actions_dialog.size_request()[0]-50, -1)
		close_button = self.actions_dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
		close_button.grab_focus()
		self.actions_dialog.run()
		self.refresh_custom_actions_menu()
		while gtk.events_pending():
			gtk.main_iteration()
		if len(self.image_list) == 0:
			self.set_image_sensitivities(False)
		self.actions_dialog.destroy()

	def add_custom_action(self, button, treeview):
		self.open_custom_action_dialog(True, '', '', 'None', False, treeview)

	def edit_custom_action2(self, treeview, path, view_column):
		self.edit_custom_action(None, treeview)

	def edit_custom_action(self, button, treeview):
		(model, iter) = self.actionwidget.get_selection().get_selected()
		if iter != None:
			(row, ) = self.actionstore.get_path(iter)
			self.open_custom_action_dialog(False, self.usettings['action_names'][row], self.usettings['action_commands'][row], self.usettings['action_shortcuts'][row], self.usettings['action_batch'][row], treeview)

	def open_custom_action_dialog(self, add_call, name, command, shortcut, batch, treeview):
		if add_call:
			self.dialog_name = gtk.Dialog(_("Add Custom Action"), self.actions_dialog, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
		else:
			self.dialog_name = gtk.Dialog(_("Edit Custom Action"), self.actions_dialog, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
		self.dialog_name.set_modal(True)
		table = gtk.Table(2, 4, False)
		action_name_label = gtk.Label(_("Action Name:"))
		action_name_label.set_alignment(0, 0.5)
		action_command_label = gtk.Label(_("Command:"))
		action_command_label.set_alignment(0, 0.5)
		shortcut_label = gtk.Label(_("Shortcut:"))
		shortcut_label.set_alignment(0, 0.5)
		table.attach(action_name_label, 0, 1, 0, 1, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(action_command_label, 0, 1, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(shortcut_label, 0, 1, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		action_name = gtk.Entry()
		action_name.set_text(name)
		action_command = gtk.Entry()
		action_command.set_text(command)
		table.attach(action_name, 1, 2, 0, 1, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(action_command, 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		self.shortcut = gtk.Button(shortcut)
		self.shortcut.connect('clicked', self.shortcut_clicked)
		table.attach(self.shortcut, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		batchmode = gtk.CheckButton(_("Perform action on all images (Batch)"))
		batchmode.set_active(batch)
		table.attach(batchmode, 0, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		self.dialog_name.vbox.pack_start(table, False, False, 5)
		self.dialog_name.vbox.show_all()
		self.dialog_name.connect('response', self.dialog_name_response, add_call, action_name, action_command, self.shortcut, batchmode, treeview)
		self.dialog_name.run()

	def dialog_name_response(self, dialog, response, add_call, action_name, action_command, shortcut, batchmode, treeview):
		if response == gtk.RESPONSE_ACCEPT:
			if not (action_command.get_text() == "" or action_name.get_text() == "" or self.shortcut.get_label() == "None"):
				name = action_name.get_text()
				command = action_command.get_text()
				if ((("[NEXT]" in command.strip()) and command.strip()[-6:] != "[NEXT]") or (("[PREV]" in command.strip()) and command.strip()[-6:] != "[PREV]") ):
					error_dialog = gtk.MessageDialog(self.actions_dialog, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('[PREV] and [NEXT] are only valid alone or at the end of the command'))
					error_dialog.set_title(_("Invalid Custom Action"))
					error_dialog.run()
					error_dialog.destroy()
					return
				shortcut = shortcut.get_label()
				batch = batchmode.get_active()
				dialog.destroy()
				if add_call:
					self.usettings['action_names'].append(name)
					self.usettings['action_commands'].append(command)
					self.usettings['action_shortcuts'].append(shortcut)
					self.usettings['action_batch'].append(batch)
				else:
					(model, iter) = self.actionwidget.get_selection().get_selected()
					(rownum, ) = self.actionstore.get_path(iter)
					self.usettings['action_names'][rownum] = name
					self.usettings['action_commands'][rownum] = command
					self.usettings['action_shortcuts'][rownum] = shortcut
					self.usettings['action_batch'][rownum] = batch
				self.populate_treeview()
				if add_call:
					rownum = len(self.usettings['action_names'])-1
				treeview.get_selection().select_path(rownum)
				while gtk.events_pending():
					gtk.main_iteration()
				# Keep item in visible rect:
				visible_rect = treeview.get_visible_rect()
				row_rect = treeview.get_background_area(rownum, self.tvcolumn1)
				if row_rect.y + row_rect.height > visible_rect.height:
					top_coord = (row_rect.y + row_rect.height - visible_rect.height) + visible_rect.y
					treeview.scroll_to_point(-1, top_coord)
				elif row_rect.y < 0:
					treeview.scroll_to_cell(rownum)
			else:
				error_dialog = gtk.MessageDialog(self.actions_dialog, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('Incomplete custom action specified.'))
				error_dialog.set_title(_("Invalid Custom Action"))
				error_dialog.run()
				error_dialog.destroy()
		else:
			dialog.destroy()

	def custom_action_move_down(self, button, treeview):
		iter = None
		selection = treeview.get_selection()
		model, iter = selection.get_selected()
		if iter:
			rownum = int(model.get_string_from_iter(iter))
			if rownum < len(self.usettings['action_names'])-1:
				# Move item down:
				temp_name = self.usettings['action_names'][rownum]
				temp_shortcut = self.usettings['action_shortcuts'][rownum]
				temp_command = self.usettings['action_commands'][rownum]
				temp_batch = self.usettings['action_batch'][rownum]
				self.usettings['action_names'][rownum] = self.usettings['action_names'][rownum+1]
				self.usettings['action_shortcuts'][rownum] = self.usettings['action_shortcuts'][rownum+1]
				self.usettings['action_commands'][rownum] = self.usettings['action_commands'][rownum+1]
				self.usettings['action_batch'][rownum] =  self.usettings['action_batch'][rownum+1]
				self.usettings['action_names'][rownum+1] = temp_name
				self.usettings['action_shortcuts'][rownum+1] = temp_shortcut
				self.usettings['action_commands'][rownum+1] = temp_command
				self.usettings['action_batch'][rownum+1] = temp_batch
				# Repopulate treeview and keep item selected:
				self.populate_treeview()
				selection.select_path((rownum+1,))
				while gtk.events_pending():
					gtk.main_iteration()
				# Keep item in visible rect:
				rownum = rownum + 1
				visible_rect = treeview.get_visible_rect()
				row_rect = treeview.get_background_area(rownum, self.tvcolumn1)
				if row_rect.y + row_rect.height > visible_rect.height:
					top_coord = (row_rect.y + row_rect.height - visible_rect.height) + visible_rect.y
					treeview.scroll_to_point(-1, top_coord)
				elif row_rect.y < 0:
					treeview.scroll_to_cell(rownum)

	def custom_action_move_up(self, button, treeview):
		iter = None
		selection = treeview.get_selection()
		model, iter = selection.get_selected()
		if iter:
			rownum = int(model.get_string_from_iter(iter))
			if rownum > 0:
				# Move item down:
				temp_name = self.usettings['action_names'][rownum]
				temp_shortcut = self.usettings['action_shortcuts'][rownum]
				temp_command = self.usettings['action_commands'][rownum]
				temp_batch = self.usettings['action_batch'][rownum]
				self.usettings['action_names'][rownum] = self.usettings['action_names'][rownum-1]
				self.usettings['action_shortcuts'][rownum] = self.usettings['action_shortcuts'][rownum-1]
				self.usettings['action_commands'][rownum] = self.usettings['action_commands'][rownum-1]
				self.usettings['action_batch'][rownum] =  self.usettings['action_batch'][rownum-1]
				self.usettings['action_names'][rownum-1] = temp_name
				self.usettings['action_shortcuts'][rownum-1] = temp_shortcut
				self.usettings['action_commands'][rownum-1] = temp_command
				self.usettings['action_batch'][rownum-1] = temp_batch
				# Repopulate treeview and keep item selected:
				self.populate_treeview()
				selection.select_path((rownum-1,))
				while gtk.events_pending():
					gtk.main_iteration()
				# Keep item in visible rect:
				rownum = rownum - 1
				visible_rect = treeview.get_visible_rect()
				row_rect = treeview.get_background_area(rownum, self.tvcolumn1)
				if row_rect.y + row_rect.height > visible_rect.height:
					top_coord = (row_rect.y + row_rect.height - visible_rect.height) + visible_rect.y
					treeview.scroll_to_point(-1, top_coord)
				elif row_rect.y < 0:
					treeview.scroll_to_cell(rownum)

	def shortcut_clicked(self, widget):
		self.dialog_shortcut = gtk.Dialog(_("Action Shortcut"), self.dialog_name, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		self.shortcut_label = gtk.Label(_("Press the desired shortcut for the action."))
		hbox = gtk.HBox()
		hbox.pack_start(self.shortcut_label, False, False, 15)
		self.dialog_shortcut.vbox.pack_start(hbox, False, False, 5)
		self.dialog_shortcut.vbox.show_all()
		self.dialog_shortcut.connect('key-press-event', self.shortcut_keypress)
		self.dialog_shortcut.run()
		self.dialog_shortcut.destroy()

	def shortcut_keypress(self, widget, event):
		shortcut = gtk.accelerator_name(event.keyval, event.state)
		if "<Mod2>" in shortcut:
			shortcut = shortcut.replace("<Mod2>", "")
		if shortcut[(len(shortcut)-2):len(shortcut)] != "_L" and shortcut[(len(shortcut)-2):len(shortcut)] != "_R":
			# Validate to make sure the shortcut hasn't already been used:
			for i in range(len(self.keys)):
				if shortcut == self.keys[i][1]:
					error_dialog = gtk.MessageDialog(self.dialog_shortcut, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('The shortcut \'%(shortcut)s\' is already used for \'%(key)s\'.') % {'shortcut': shortcut, 'key': self.keys[i][0]})
					error_dialog.set_title(_("Invalid Shortcut"))
					error_dialog.run()
					error_dialog.destroy()
					return
			for i in range(len(self.usettings['action_shortcuts'])):
				if shortcut == self.usettings['action_shortcuts'][i]:
					error_dialog = gtk.MessageDialog(self.dialog_shortcut, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('The shortcut \'%(shortcut)s\' is already used for \'%(key)s\'.') % {'shortcut': shortcut, 'key': self.usettings['action_names'][i]})
					error_dialog.set_title(_("Invalid Shortcut"))
					error_dialog.run()
					error_dialog.destroy()
					return
			self.shortcut.set_label(shortcut)
			widget.destroy()

	def remove_custom_action(self, button):
		(model, iter) = self.actionwidget.get_selection().get_selected()
		if iter != None:
			(row, ) = self.actionstore.get_path(iter)
			self.usettings['action_names'].pop(row)
			self.usettings['action_shortcuts'].pop(row)
			self.usettings['action_commands'].pop(row)
			self.usettings['action_batch'].pop(row)
			self.populate_treeview()
			self.actionwidget.grab_focus()

	def populate_treeview(self):
		self.actionstore.clear()
		for i in range(len(self.usettings['action_names'])):
			if self.usettings['action_batch'][i]:
				pb = gtk.STOCK_APPLY
			else:
				pb = None
			self.actionstore.append([pb, '<big><b>' + self.usettings['action_names'][i].replace('&','&amp;') + '</b></big>\n<small>' + self.usettings['action_commands'][i].replace('&','&amp;') + '</small>', self.usettings['action_shortcuts'][i]])
		self.tvcolumn0.clear()
		self.tvcolumn1.clear()
		self.tvcolumn2.clear()
		self.tvcolumn0.pack_start(self.cellbool)
		self.tvcolumn1.pack_start(self.cell)
		self.tvcolumn2.pack_start(self.cell)
		self.tvcolumn0.add_attribute(self.cellbool, "stock-id", 0)
		self.tvcolumn1.set_attributes(self.cell, markup=1)
		self.tvcolumn2.set_attributes(self.cell, text=2)
		self.tvcolumn1.set_expand(True)

	def screenshot(self, action):
		cancel = self.autosave_image()
		if cancel:
			return
		# Dialog:
		dialog = gtk.Dialog(_("Screenshot"), self.window, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		snapbutton = dialog.add_button(_("_Snap"), gtk.RESPONSE_ACCEPT)
		snapimage = gtk.Image()
		snapimage.set_from_stock(gtk.STOCK_OK, gtk.ICON_SIZE_BUTTON)
		snapbutton.set_image(snapimage)
		loc = gtk.Label()
		loc.set_markup('<b>' + _('Location') + '</b>')
		loc.set_alignment(0, 0)
		area = gtk.RadioButton()
		area1 = gtk.RadioButton(group=area, label=_("Entire screen"))
		area2 = gtk.RadioButton(group=area, label=_("Window under pointer"))
		if not HAS_XMOUSE:
			area2.set_sensitive(False)
		area1.set_active(True)
		de = gtk.Label()
		de.set_markup('<b>' + _("Delay") + '</b>')
		de.set_alignment(0, 0)
		delaybox = gtk.HBox()
		adj = gtk.Adjustment(self.usettings['screenshot_delay'], 0, 30, 1, 10, 0)
		delay = gtk.SpinButton(adj, 0, 0)
		delay.set_numeric(True)
		delay.set_update_policy(gtk.UPDATE_IF_VALID)
		delay.set_wrap(False)
		delaylabel = gtk.Label(_(" seconds"))
		delaybox.pack_start(delay, False)
		delaybox.pack_start(delaylabel, False)
		table = gtk.Table()
		table.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table.attach(loc, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(gtk.Label(), 1, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table.attach(area1, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(area2, 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(gtk.Label(), 1, 2, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(de, 1, 2, 7, 8,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(gtk.Label(), 1, 2, 8, 9,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(delaybox, 1, 2, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(gtk.Label(), 1, 2, 10, 11,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		dialog.vbox.pack_start(table)
		dialog.set_default_response(gtk.RESPONSE_ACCEPT)
		dialog.vbox.show_all()
		response = dialog.run()
		if response == gtk.RESPONSE_ACCEPT:
			dialog.destroy()
			while gtk.events_pending():
				gtk.main_iteration()
			self.usettings['screenshot_delay'] = delay.get_value_as_int()
			gobject.timeout_add(int(self.usettings['screenshot_delay']*1000), self._screenshot_grab, area1.get_active())
		else:
			dialog.destroy()

	def _screenshot_grab(self, entire_screen):
		root_win = gtk.gdk.get_default_root_window()
		if entire_screen:
			x = 0
			y = 0
			width = gtk.gdk.screen_width()
			height = gtk.gdk.screen_height()
		else:
			(x, y, width, height) = xmouse.geometry()
		pix = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, width, height)
		pix = pix.get_from_drawable(root_win, gtk.gdk.colormap_get_system(), x, y, 0, 0, width, height)
		# Save as /tmp/mirage-<random>/filename.ext
		tmpdir = tempfile.mkdtemp(prefix="mirage-") + "/"
		tmpfile = tmpdir + "screenshot.png"
		pix.save(tmpfile, 'png')
		# Load file:
		self.image_list = [tmpfile]
		self.curr_img_in_list = 0
		gobject.idle_add(self.load_new_image2, False, False, False, False, True)
		self.update_statusbar()
		self.set_go_navigation_sensitivities(False)
		self.set_slideshow_sensitivities()
		self.thumbpane_update_images(True, self.curr_img_in_list)
		del pix
		self.window.present()

	def show_properties(self, action):
		show_props = gtk.Dialog(_("Properties"), self.window)
		show_props.set_has_separator(False)
		show_props.set_resizable(False)
		table = gtk.Table(3, 4, False)
		image = gtk.Image()
		if self.currimg.animation:
			pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original.get_static_image(), 180, self.zoom_quality)
		else:
			pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original, 180, self.zoom_quality)
		image.set_from_pixbuf(self.pixbuf_add_border(pixbuf))

		# The generic info
		vbox_left = gtk.VBox()
		title = gtk.Label(_("Generic:"))
		title.set_alignment(1, 1)
		filename = gtk.Label(_("File name:"))
		filename.set_alignment(1, 1)
		filedate = gtk.Label(_("File modified:"))
		filedate.set_alignment(1, 1)
		imagesize = gtk.Label(_("Dimensions:"))
		imagesize.set_alignment(1, 1)
		filesize = gtk.Label(_("File size:"))
		filesize.set_alignment(1, 1)
		filetype = gtk.Label(_("File type:"))
		filetype.set_alignment(1, 1)
		transparency = gtk.Label(_("Transparency:"))
		transparency.set_alignment(1, 1)
		animation = gtk.Label(_("Animation:"))
		animation.set_alignment(1, 1)
		bits = gtk.Label(_("Bits per sample:"))
		bits.set_alignment(1, 1)
		channels = gtk.Label(_("Channels:"))
		channels.set_alignment(1, 1)
		vbox_left.pack_start(title, False, False, 2)
		vbox_left.pack_start(filename, False, False, 2)
		vbox_left.pack_start(filedate, False, False, 2)
		vbox_left.pack_start(imagesize, False, False, 2)
		vbox_left.pack_start(filesize, False, False, 2)
		vbox_left.pack_start(filetype, False, False, 2)
		vbox_left.pack_start(transparency, False, False, 2)
		vbox_left.pack_start(animation, False, False, 2)
		vbox_left.pack_start(bits, False, False, 2)
		vbox_left.pack_start(channels, False, False, 2)
		vbox_right = gtk.VBox()
		filestat = os.stat(self.currimg.name)
		filename2 = gtk.Label(os.path.basename(self.currimg.name))
		filedate2 = gtk.Label(time.strftime('%Y/%m/%d  %H:%M', time.localtime(filestat[stat.ST_MTIME])))
		imagesize2 = gtk.Label(str(self.currimg.pixbuf_original.get_width()) + "x" + str(self.currimg.pixbuf_original.get_height()))
		filetype2 = gtk.Label(self.currimg.fileinfo['mime_types'][0])
		filesize2 = gtk.Label(str(filestat[stat.ST_SIZE]/1000) + "KB")
		if not self.currimg.animation and pixbuf.get_has_alpha():
			transparency2 = gtk.Label(_("Yes"))
		else:
			transparency2 = gtk.Label(_("No"))
		if self.currimg.animation:
			animation2 = gtk.Label(_("Yes"))
		else:
			animation2 = gtk.Label(_("No"))
		bits2 = gtk.Label(str(pixbuf.get_bits_per_sample()))
		channels2 = gtk.Label(str(pixbuf.get_n_channels()))
		filename2.set_alignment(0, 1)
		filedate2.set_alignment(0, 1)
		imagesize2.set_alignment(0, 1)
		filesize2.set_alignment(0, 1)
		filetype2.set_alignment(0, 1)
		transparency2.set_alignment(0, 1)
		animation2.set_alignment(0, 1)
		bits2.set_alignment(0, 1)
		channels2.set_alignment(0, 1)
		empty = gtk.Label(" ") # An empty label to align the rows correctly
		vbox_right.pack_start(empty, False, False, 2)
		vbox_right.pack_start(filename2, False, False, 2)
		vbox_right.pack_start(filedate2, False, False, 2)
		vbox_right.pack_start(imagesize2, False, False, 2)
		vbox_right.pack_start(filesize2, False, False, 2)
		vbox_right.pack_start(filetype2, False, False, 2)
		vbox_right.pack_start(transparency2, False, False, 2)
		vbox_right.pack_start(animation2, False, False, 2)
		vbox_right.pack_start(bits2, False, False, 2)
		vbox_right.pack_start(channels2, False, False, 2)
		hbox = gtk.HBox()
		hbox.pack_start(vbox_left, False, False, 3)
		hbox.pack_start(vbox_right, False, False, 3)
		includes_exif = False
		if HAS_EXIF:
			exifd = pyexiv2.ImageMetadata(self.currimg.name)
			exifd.read()
			if ([x for x in exifd.exif_keys if "Exif.Photo" in x]):
				includes_exif = True
				# The exif data
				exif_lbox = gtk.VBox()
				exif_title = gtk.Label(_("Exifdata"))
				exif_title.set_alignment(1,1)
				#for line alignment
				exif_vbox = gtk.VBox()
				exif_empty = gtk.Label(" ")

				expo_l, expo_v = self.exif_return_label(exifd, _("Exposure time:"), _("%s sec"),"Exif.Photo.ExposureTime", "rat_frac")
				aperture_l, aperture_v = self.exif_return_label(exifd, _("Aperture:"), _("%s"),"Exif.Photo.FNumber", "rat_float")
				focal_l, focal_v = self.exif_return_label(exifd, _("Focal length:"), _("%s mm"),"Exif.Photo.FocalLength", "rat_int")
				date_l, date_v = self.exif_return_label(exifd, _("Time taken:"), _("%s"),"Exif.Photo.DateTimeOriginal", "str")
				ISO_l, ISO_v = self.exif_return_label(exifd, _("ISO Speed:"), _("%s"),"Exif.Photo.ISOSpeedRatings", "int")
				bias_l, bias_v = self.exif_return_label(exifd, _("Exposure bias:"), _("%s"),"Exif.Photo.ExposureBiasValue", "rat_frac")
				model_l, model_v = self.exif_return_label(exifd, _("Camera:"), _("%s"),"Exif.Image.Model", "str")
				exif_lbox.pack_start(exif_title, False, False, 2)
				exif_lbox.pack_start(aperture_l, False, False, 2)
				exif_lbox.pack_start(focal_l, False, False, 2)
				exif_lbox.pack_start(expo_l, False, False, 2)
				exif_lbox.pack_start(bias_l, False, False, 2)
				exif_lbox.pack_start(ISO_l, False, False, 2)
				exif_lbox.pack_start(model_l, False, False, 2)
				exif_lbox.pack_start(date_l, False, False, 2)

				exif_vbox.pack_start(exif_empty, False, False, 2)
				exif_vbox.pack_start(aperture_v, False, False, 2)
				exif_vbox.pack_start(focal_v, False, False, 2)
				exif_vbox.pack_start(expo_v, False, False, 2)
				exif_vbox.pack_start(bias_v, False, False, 2)
				exif_vbox.pack_start(ISO_v, False, False, 2)
				exif_vbox.pack_start(model_v, False, False, 2)
				exif_vbox.pack_start(date_v, False, False, 2)

				hbox2 = gtk.HBox()
				hbox2.pack_start(exif_lbox, False, False, 2)
				hbox2.pack_start(exif_vbox, False, False, 2)

		#Show the box
		table.attach(image, 1, 2, 1, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(hbox, 2, 3, 1, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		if HAS_EXIF and includes_exif:
			table.attach(hbox2, 3, 4, 1, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		show_props.vbox.pack_start(table, False, False, 15)
		show_props.vbox.show_all()
		close_button = show_props.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
		close_button.grab_focus()
		show_props.run()
		show_props.destroy()

	def exif_return_label(self, exif, label_v, format, tag, type="str"):
		label = gtk.Label(label_v)
		label.set_alignment(1, 1)
		if tag in exif.exif_keys:
			raw = exif[tag].value
			if type == "rat_frac":
				val = Fraction(str(raw))
			elif type == "rat_float":
				val = float(raw)
			elif type == "rat_int":
				val = int(raw)
			elif type == "int":
				val = int(raw)
			else:
				val = raw
			value = gtk.Label(format % str(val))
		else:
			value = gtk.Label("-")
		value.set_alignment(0,1)
		return label, value

	def show_prefs(self, action):
		prev_thumbnail_size = self.usettings['thumbnail_size']
		self.prefs_dialog = gtk.Dialog(_("%s Preferences") % __appname__, self.window)
		self.prefs_dialog.set_has_separator(False)
		self.prefs_dialog.set_resizable(False)
		# "Interface" prefs:
		table_settings = gtk.Table(14, 3, False)
		bglabel = gtk.Label()
		bglabel.set_markup('<b>' + _('Interface') + '</b>')
		bglabel.set_alignment(0, 1)
		color_hbox = gtk.HBox(False, 0)
		colortext = gtk.Label(_('Background color:'))
		self.colorbutton = gtk.ColorButton(self.bgcolor)
		self.colorbutton.connect('color-set', self.bgcolor_selected)
		self.colorbutton.set_size_request(150, -1)
		self.colorbutton.set_tooltip_text(_("Sets the background color for the application."))
		color_hbox.pack_start(colortext, False, False, 0)
		color_hbox.pack_start(self.colorbutton, False, False, 0)
		color_hbox.pack_start(gtk.Label(), True, True, 0)

		simplecolor_hbox = gtk.HBox(False, 0)
		simplecolortext = gtk.Label(_('Simple background color:'))
		simplecolorbutton = gtk.CheckButton()
		simplecolorbutton.connect('toggled', self.simple_bgcolor_selected)
		simplecolor_hbox.pack_start(simplecolortext, False, False, 0)
		simplecolor_hbox.pack_start(simplecolorbutton, False, False, 0)
		simplecolor_hbox.pack_start(gtk.Label(), True, True, 0)
		if self.usettings['simple_bgcolor']:
				simplecolorbutton.set_active(True)

		fullscreen = gtk.CheckButton(_("Open Mirage in fullscreen mode"))
		fullscreen.set_active(self.usettings['start_in_fullscreen'])
		thumbbox = gtk.HBox()
		thumblabel = gtk.Label(_("Thumbnail size:"))
		thumbbox.pack_start(thumblabel, False, False, 0)
		thumbsize = gtk.combo_box_new_text()
		option = 0
		for size in self.thumbnail_sizes:
			thumbsize.append_text(size + " x " + size)
			if self.usettings['thumbnail_size'] == int(size):
				thumbsize.set_active(option)
			option += 1
		thumbbox.pack_start(thumbsize, False, False, 5)
		table_settings.attach(gtk.Label(), 1, 3, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_settings.attach(bglabel, 1, 3, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_settings.attach(gtk.Label(), 1, 3, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_settings.attach(simplecolor_hbox, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(color_hbox, 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_settings.attach(thumbbox, 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 8, 9,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(fullscreen, 1, 3, 9, 10,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 11, 12,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 12, 13,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 13, 14,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_settings.attach(gtk.Label(), 1, 3, 14, 15,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		# "Behavior" tab:
		table_behavior = gtk.Table(14, 2, False)
		openlabel = gtk.Label()
		openlabel.set_markup('<b>' + _('Open Behavior') + '</b>')
		openlabel.set_alignment(0, 1)
		hbox_openmode = gtk.HBox()
		hbox_openmode.pack_start(gtk.Label(_('Open new image in:')), False, False, 0)
		combobox = gtk.combo_box_new_text()
		combobox.append_text(_("Smart Mode"))
		combobox.append_text(_("Zoom To Fit Mode"))
		combobox.append_text(_("1:1 Mode"))
		combobox.append_text(_("Last Active Mode"))
		combobox.set_active(self.usettings['open_mode'])
		hbox_openmode.pack_start(combobox, False, False, 5)
		openallimages = gtk.CheckButton(_("Load all images in current directory"))
		openallimages.set_active(self.usettings['open_all_images'])
		openallimages.set_tooltip_text(_("If enabled, opening an image in Mirage will automatically load all images found in that image's directory."))
		hiddenimages = gtk.CheckButton(_("Allow loading hidden files"))
		hiddenimages.set_active(self.usettings['open_hidden_files'])
		hiddenimages.set_tooltip_text(_("If checked, Mirage will open hidden files. Otherwise, hidden files will be ignored."))
		#Numacomp sorting options
		usenumacomp = gtk.CheckButton(_("Use Numerical aware sort"))
		usenumacomp.set_active(self.usettings['use_numacomp'])
		usenumacomp.set_tooltip_text(_("If checked, Mirage will sort the images based on a numerical aware sort."))
		usenumacomp.set_sensitive(HAVE_NUMACOMP)
		case_numacomp = gtk.CheckButton(_("Casesensitive sort"))
		case_numacomp.set_active(self.usettings['case_numacomp'])
		case_numacomp.set_tooltip_text(_("If checked, a case-sensitive sort will be used"))
		case_numacomp.set_sensitive(usenumacomp.get_active())
		usenumacomp.connect('toggled', self.toggle_sensitivy_of_other,case_numacomp)

		openpref = gtk.RadioButton()
		openpref1 = gtk.RadioButton(group=openpref, label=_("Use last chosen directory"))
		openpref1.set_tooltip_text(_("The default 'Open' directory will be the last directory used."))
		openpref2 = gtk.RadioButton(group=openpref, label=_("Use this fixed directory:"))
		openpref2.connect('toggled', self.prefs_use_fixed_dir_clicked)
		openpref2.set_tooltip_text(_("The default 'Open' directory will be this specified directory."))
		hbox_defaultdir = gtk.HBox()
		self.defaultdir = gtk.Button()
		hbox_defaultdir.pack_start(gtk.Label(), True, True, 0)
		hbox_defaultdir.pack_start(self.defaultdir, False, False, 0)
		hbox_defaultdir.pack_start(gtk.Label(), True, True, 0)
		if len(self.usettings['fixed_dir']) > 25:
			self.defaultdir.set_label('...' + self.usettings['fixed_dir'][-22:])
		else:
			self.defaultdir.set_label(self.usettings['fixed_dir'])
		self.defaultdir.connect('clicked', self.defaultdir_clicked)
		self.defaultdir.set_size_request(250, -1)
		if self.usettings['use_last_dir']:
			openpref1.set_active(True)
			self.defaultdir.set_sensitive(False)
		else:
			openpref2.set_active(True)
			self.defaultdir.set_sensitive(True)
		table_behavior.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_behavior.attach(openlabel, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_behavior.attach(gtk.Label(), 1, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_behavior.attach(hbox_openmode, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(gtk.Label(), 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_behavior.attach(openallimages, 1, 2, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(hiddenimages, 1, 2, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(usenumacomp, 1, 2, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(case_numacomp, 1, 2, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 50, 0)
		table_behavior.attach(gtk.Label(), 1, 2, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_behavior.attach(openpref1, 1, 2, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(openpref2, 1, 2, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_behavior.attach(hbox_defaultdir, 1, 2, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 45, 0)
		table_behavior.attach(gtk.Label(), 1, 2, 14, 15, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 45, 0)

		# "Navigation" tab:
		table_navigation = gtk.Table(14, 2, False)
		navlabel = gtk.Label()
		navlabel.set_markup('<b>' + _('Navigation') + '</b>')
		navlabel.set_alignment(0, 1)
		preloadnav = gtk.CheckButton(label=_("Preload images for faster navigation"))
		preloadnav.set_active(self.usettings['preloading_images'])
		preloadnav.set_tooltip_text(_("If enabled, the next and previous images in the list will be preloaded during idle time. Note that the speed increase comes at the expense of memory usage, so it is recommended to disable this option on machines with limited ram."))
		hbox_listwrap = gtk.HBox()
		hbox_listwrap.pack_start(gtk.Label(_("Wrap around imagelist:")), False, False, 0)
		combobox2 = gtk.combo_box_new_text()
		combobox2.append_text(_("No"))
		combobox2.append_text(_("Yes"))
		combobox2.append_text(_("Prompt User"))
		combobox2.set_active(self.usettings['listwrap_mode'])
		hbox_listwrap.pack_start(combobox2, False, False, 5)
		table_navigation.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(navlabel, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(hbox_listwrap, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(preloadnav, 1, 2, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_navigation.attach(gtk.Label(), 1, 2, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		# "Slideshow" tab:
		table_slideshow = gtk.Table(14, 2, False)
		slideshowlabel = gtk.Label()
		slideshowlabel.set_markup('<b>' + _('Slideshow Mode') + '</b>')
		slideshowlabel.set_alignment(0, 1)
		hbox_delay = gtk.HBox()
		hbox_delay.pack_start(gtk.Label(_("Delay between images in seconds:")), False, False, 0)
		spin_adj = gtk.Adjustment(self.usettings['slideshow_delay'], 0, 50000, 1, 10, 0)
		delayspin = gtk.SpinButton(spin_adj, 1.0, 0)
		delayspin.set_numeric(True)
		hbox_delay.pack_start(delayspin, False, False, 5)
		randomize = gtk.CheckButton(_("Randomize order of images"))
		randomize.set_active(self.usettings['slideshow_random'])
		randomize.set_tooltip_text(_("If enabled, a random image will be chosen during slideshow mode (without loading any image twice)."))
		disable_screensaver = gtk.CheckButton(_("Disable screensaver in slideshow mode"))
		disable_screensaver.set_active(self.usettings['disable_screensaver'])
		disable_screensaver.set_tooltip_text(_("If enabled, xscreensaver will be temporarily disabled during slideshow mode."))
		ss_in_fs = gtk.CheckButton(_("Always start in fullscreen mode"))
		ss_in_fs.set_tooltip_text(_("If enabled, starting a slideshow will put the application in fullscreen mode."))
		ss_in_fs.set_active(self.usettings['slideshow_in_fullscreen'])
		table_slideshow.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(slideshowlabel, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(hbox_delay, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(disable_screensaver, 1, 2, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_slideshow.attach(ss_in_fs, 1, 2, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_slideshow.attach(randomize, 1, 2, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		table_slideshow.attach(gtk.Label(), 1, 2, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 0, 0)
		# "Image" tab:
		table_image = gtk.Table(14, 2, False)
		imagelabel = gtk.Label()
		imagelabel.set_markup('<b>' + _('Image Editing') + '</b>')
		imagelabel.set_alignment(0, 1)
		deletebutton = gtk.CheckButton(_("Confirm image delete"))
		deletebutton.set_active(self.usettings['confirm_delete'])

		zoom_hbox = gtk.HBox()
		zoom_hbox.pack_start(gtk.Label(_('Scaling quality:')), False, False, 0)
		zoomcombo = gtk.combo_box_new_text()
		zoomcombo.append_text(_("Nearest (Fastest)"))
		zoomcombo.append_text(_("Tiles"))
		zoomcombo.append_text(_("Bilinear"))
		zoomcombo.append_text(_("Hyper (Best)"))
		zoomcombo.set_active(self.usettings['zoomvalue'])
		zoom_hbox.pack_start(zoomcombo, False, False, 0)
		zoom_hbox.pack_start(gtk.Label(), True, True, 0)

		hbox_save = gtk.HBox()
		savelabel = gtk.Label(_("Modified images:"))
		savecombo = gtk.combo_box_new_text()
		savecombo.append_text(_("Ignore Changes"))
		savecombo.append_text(_("Auto-Save"))
		savecombo.append_text(_("Prompt For Action"))
		savecombo.set_active(self.usettings['savemode'])
		hbox_save.pack_start(savelabel, False, False, 0)
		hbox_save.pack_start(savecombo, False, False, 5)

		hbox_quality = gtk.HBox()
		qualitylabel = gtk.Label(_("Quality to save in:"))
		qspin_adj = gtk.Adjustment(self.usettings['quality_save'], 0, 100, 1, 100, 0)
		qualityspin = gtk.SpinButton(qspin_adj, 1.0, 0)
		qualityspin.set_numeric(True)
		hbox_quality.pack_start(qualitylabel, False, False, 0)
		hbox_quality.pack_start(qualityspin, False, False, 5)
		table_image.attach(gtk.Label(), 1, 3, 1, 2,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(imagelabel, 1, 3, 2, 3,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table_image.attach(gtk.Label(), 1, 3, 3, 4,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(zoom_hbox, 1, 3, 4, 5,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 5, 6,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(hbox_save, 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(hbox_quality, 1, 3, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 9, 10,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(deletebutton, 1, 3, 10, 11,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 11, 12,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 12, 13,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 13, 14,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table_image.attach(gtk.Label(), 1, 3, 14, 15,  gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		# Add tabs:
		notebook = gtk.Notebook()
		notebook.append_page(table_behavior, gtk.Label(_("Behavior")))
		notebook.append_page(table_navigation, gtk.Label(_("Navigation")))
		notebook.append_page(table_settings, gtk.Label(_("Interface")))
		notebook.append_page(table_slideshow, gtk.Label(_("Slideshow")))
		notebook.append_page(table_image, gtk.Label(_("Image")))
		notebook.set_current_page(0)
		hbox = gtk.HBox()
		self.prefs_dialog.vbox.pack_start(hbox, False, False, 7)
		hbox.pack_start(notebook, False, False, 7)
		notebook.connect('switch-page', self.prefs_tab_switched)
		# Show prefs:
		self.prefs_dialog.vbox.show_all()
		self.close_button = self.prefs_dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
		self.close_button.grab_focus()
		response = self.prefs_dialog.run()
		if response == gtk.RESPONSE_CLOSE or response == gtk.RESPONSE_DELETE_EVENT:
			self.usettings['zoomvalue'] = zoomcombo.get_active()
			if int(round(self.usettings['zoomvalue'], 0)) == 0:
				self.zoom_quality = gtk.gdk.INTERP_NEAREST
			elif int(round(self.usettings['zoomvalue'], 0)) == 1:
				self.zoom_quality = gtk.gdk.INTERP_TILES
			elif int(round(self.usettings['zoomvalue'], 0)) == 2:
				self.zoom_quality = gtk.gdk.INTERP_BILINEAR
			elif int(round(self.usettings['zoomvalue'], 0)) == 3:
				self.zoom_quality = gtk.gdk.INTERP_HYPER
			self.usettings['open_all_images'] = openallimages.get_active()
			self.usettings['open_hidden_files'] = hiddenimages.get_active()
			self.usettings['use_numacomp'] = usenumacomp.get_active()
			self.usettings['case_numacomp'] = case_numacomp.get_active()
			if openpref1.get_active():
				self.usettings['use_last_dir'] = True
			else:
				self.usettings['use_last_dir'] = False
			open_mode_prev = self.usettings['open_mode']
			self.usettings['open_mode'] = combobox.get_active()
			preloading_images_prev = self.usettings['preloading_images']
			self.usettings['preloading_images'] = preloadnav.get_active()
			self.usettings['listwrap_mode'] = combobox2.get_active()
			self.usettings['slideshow_delay'] = delayspin.get_value()
			self.curr_slideshow_delay = self.usettings['slideshow_delay']
			self.usettings['slideshow_random'] = randomize.get_active()
			self.curr_slideshow_random = self.usettings['slideshow_random']
			self.usettings['disable_screensaver'] = disable_screensaver.get_active()
			self.usettings['slideshow_in_fullscreen'] = ss_in_fs.get_active()
			self.usettings['savemode'] = savecombo.get_active()
			self.usettings['start_in_fullscreen'] = fullscreen.get_active()
			self.usettings['confirm_delete'] = deletebutton.get_active()
			self.usettings['quality_save'] = qualityspin.get_value()
			self.usettings['thumbnail_size'] = int(self.thumbnail_sizes[thumbsize.get_active()])
			if self.usettings['thumbnail_size'] != prev_thumbnail_size:
				gobject.idle_add(self.thumbpane_set_size)
				gobject.idle_add(self.thumbpane_update_images, True, self.curr_img_in_list)
			self.prefs_dialog.destroy()
			self.set_go_navigation_sensitivities(False)
			if (self.usettings['preloading_images'] and not preloading_images_prev) or (open_mode_prev != self.usettings['open_mode']):
				# The user just turned on preloading, so do it:
				self.nextimg.index = -1
				self.previmg.index = -1
				self.preload_when_idle = gobject.idle_add(self.preload_next_image, False)
				self.preload_when_idle2 = gobject.idle_add(self.preload_prev_image, False)
			elif not self.usettings['preloading_images']:
				self.nextimg.index = -1
				self.previmg.index = -1

	def prefs_use_fixed_dir_clicked(self, button):
		if button.get_active():
			self.defaultdir.set_sensitive(True)
		else:
			self.defaultdir.set_sensitive(False)

	def toggle_sensitivy_of_other(self,toggled_button,to_sensitive):
		"""Set widget to_sensitive as sensitive if toggled_button is active."""
		if toggled_button.get_active():
			to_sensitive.set_sensitive(True)
		else:
			to_sensitive.set_sensitive(False)

	def rename_image(self, action):
		if len(self.image_list) > 0:
			temp_slideshow_mode = self.slideshow_mode
			if self.slideshow_mode:
				self.toggle_slideshow(None)
			rename_dialog = gtk.Dialog(_('Rename Image'), self.window, gtk.DIALOG_MODAL)
			rename_txt = gtk.Entry()
			filename = os.path.basename(self.currimg.name)
			rename_txt.set_text(filename)
			rename_txt.set_activates_default(True)
			cancelbutton = rename_dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
			renamebutton = rename_dialog.add_button(_("_Rename"), gtk.RESPONSE_ACCEPT)
			renameimage = gtk.Image()
			renameimage.set_from_stock(gtk.STOCK_OK, gtk.ICON_SIZE_BUTTON)
			renamebutton.set_image(renameimage)
			if self.currimg.animation:
				pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original.get_static_image(), 60, self.zoom_quality)
			else:
				pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original, 60, self.zoom_quality)
			image = gtk.Image()
			image.set_from_pixbuf(pixbuf)
			instructions = gtk.Label(_("Enter the new name:"))
			instructions.set_alignment(0, 1)
			hbox = gtk.HBox()
			hbox.pack_start(image, False, False, 10)
			vbox_stuff = gtk.VBox()
			vbox_stuff.pack_start(gtk.Label(), False, False, 0)
			vbox_stuff.pack_start(instructions, False, False, 0)
			vbox_stuff.pack_start(gtk.Label(), False, False, 0)
			vbox_stuff.pack_start(rename_txt, True, True, 0)
			vbox_stuff.pack_start(gtk.Label(), False, False, 0)
			hbox.pack_start(vbox_stuff, True, True, 10)
			rename_dialog.vbox.pack_start(hbox, False, False, 0)
			rename_dialog.set_has_separator(True)
			rename_dialog.set_default_response(gtk.RESPONSE_ACCEPT)
			rename_dialog.set_size_request(300, -1)
			rename_dialog.vbox.show_all()
			rename_dialog.connect('show', self.select_rename_text, rename_txt)
			rename_dialog.connect('response', self.on_rename_dialog_response,rename_txt)
			response = rename_dialog.run()
			rename_dialog.destroy()
			if temp_slideshow_mode:
				self.toggle_slideshow(None)

	def select_rename_text(self, widget,rename_entry):
		filename = os.path.basename(self.currimg.name)
		fileext = os.path.splitext(os.path.basename(self.currimg.name))[1]
		rename_entry.select_region(0, len(filename) - len(fileext))
		
	def on_rename_dialog_response(self, dialog, response, rename_entry):
		if response == gtk.RESPONSE_ACCEPT:
			try:
				new_filename = os.path.join(os.path.dirname(self.currimg.name), rename_entry.get_text().decode('utf-8'))
				if os.path.exists(new_filename):
					exists_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_OK_CANCEL, _('Overwrite existing file %s?') % new_filename)
					exists_dialog.set_title(_("File exists"))
					resp = exists_dialog.run()
					if resp != gtk.RESPONSE_OK:
						exists_dialog.destroy()
						dialog.emit_stop_by_name('response')
						return
					exists_dialog.destroy()
				shutil.move(self.currimg.name, new_filename)
				# Update thumbnail filename:
				try:
					shutil.move(self_get_name(self.currimg.name)[1], self.thumbnail_get_name(new_filename)[1])
				except:
					pass
				self.recent_file_remove_and_refresh_name(self.currimg.name)
				self.currimg.name = new_filename
				self.register_file_with_recent_docs(self.currimg.name)
				self.image_list[self.curr_img_in_list] = new_filename
				self.update_title()
				dialog.destroy()
			except:
				error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_OK, _('Unable to rename %s') % self.currimg.name)
				error_dialog.set_title(_("Unable to rename"))
				error_dialog.run()
				error_dialog.destroy()
				dialog.emit_stop_by_name('response')

	def delete_image(self, action):
		if len(self.image_list) > 0:
			temp_slideshow_mode = self.slideshow_mode
			if self.slideshow_mode:
				self.toggle_slideshow(None)
			delete_dialog = gtk.Dialog(_('Delete Image'), self.window, gtk.DIALOG_MODAL)
			if self.usettings['confirm_delete']:
				permlabel = gtk.Label(_('Are you sure you wish to permanently delete %s?') % os.path.split(self.currimg.name)[1])
				permlabel.set_line_wrap(True)
				permlabel.set_alignment(0, 0.1)
				warningicon = gtk.Image()
				warningicon.set_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_DIALOG)
				hbox = gtk.HBox()
				hbox.pack_start(warningicon, False, False, 10)
				hbox.pack_start(permlabel, False, False, 10)
				delete_dialog.vbox.pack_start(gtk.Label(), False, False, 0)
				delete_dialog.vbox.pack_start(hbox, False, False, 0)
				cancelbutton = delete_dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
				deletebutton = delete_dialog.add_button(gtk.STOCK_DELETE, gtk.RESPONSE_YES)
				delete_dialog.set_has_separator(False)
				deletebutton.set_property('has-focus', True)
				delete_dialog.set_default_response(gtk.RESPONSE_YES)
				delete_dialog.vbox.show_all()
				response = delete_dialog.run()
			else:
				response = gtk.RESPONSE_YES
			if response  == gtk.RESPONSE_YES:
				try:
					os.remove(self.currimg.name)
					self.image_modified = False
					try:
						os.remove(self.thumbnail_get_name(self.currimg.name)[1])
					except:
						pass
					self.recent_file_remove_and_refresh_name(self.currimg.name)
					iter = self.thumblist.get_iter((self.curr_img_in_list,))
					try:
						self.thumbnail_loaded.pop(self.curr_img_in_list)
						self.thumbpane_update_images()
					except:
						pass
					
					#Decrease the subfolder indexes of folders after the current folder
					myidx = self.get_firstimgindex_curr_next_prev_subfolder(self.curr_img_in_list)[0]
					if myidx >= 0 and myidx < self.firstimgindex_subfolders_list[-1]:
						for idx in xrange(1+self.firstimgindex_subfolders_list.index(myidx),
								len(self.firstimgindex_subfolders_list)):
							#Decrease the idxes in the list
							self.firstimgindex_subfolders_list[idx] -= 1
						omgset = set(self.firstimgindex_subfolders_list)
						self.firstimgindex_subfolders_list = sorted(list(omgset))
					
					self.thumblist.remove(iter)
					templist = self.image_list
					self.image_list = []
					for item in templist:
						if item != self.currimg.name:
							self.image_list.append(item)
					if len(self.image_list) >= 1:
						if len(self.image_list) == 1:
							self.curr_img_in_list = 0
						elif self.curr_img_in_list == len(self.image_list):
							self.curr_img_in_list -= 1
						self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
						self.previmg.index = -1
						self.nextimg.index = -1
						self.load_when_idle = gobject.idle_add(self.load_new_image, False, False, True, True, True, True)
						self.set_go_navigation_sensitivities(False)
					else:
						self.imageview.clear()
						self.update_title()
						self.statusbar.push(self.statusbar.get_context_id(""), "")
						self.image_loaded = False
						self.set_slideshow_sensitivities()
						self.set_image_sensitivities(False)
						self.set_go_navigation_sensitivities(False)
					# Select new item:
					self.thumbpane_select(self.curr_img_in_list)
				except:
					error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_OK, _('Unable to delete %s') % self.currimg.name)
					error_dialog.set_title(_("Unable to delete"))
					error_dialog.run()
					error_dialog.destroy()
			delete_dialog.destroy()
			if temp_slideshow_mode:
				self.toggle_slideshow(None)

	def defaultdir_clicked(self, button):
		getdir = gtk.FileChooserDialog(title=_("Choose directory"),action=gtk.FILE_CHOOSER_ACTION_OPEN,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK))
		getdir.set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)
		getdir.set_filename(self.usettings['fixed_dir'])
		getdir.set_default_response(gtk.RESPONSE_OK)
		response = getdir.run()
		if response == gtk.RESPONSE_OK:
			self.usettings['fixed_dir'] = getdir.get_filenames()[0]
			if len(self.usettings['fixed_dir']) > 25:
				button.set_label('...' + self.usettings['fixed_dir'][-22:])
			else:
				button.set_label(self.usettings['fixed_dir'])
			getdir.destroy()
		else:
			getdir.destroy()

	def prefs_tab_switched(self, notebook, page, page_num):
		do_when_idle = gobject.idle_add(self.grab_close_button)

	def grab_close_button(self):
		self.close_button.grab_focus()

	def bgcolor_selected(self, widget):
		# When the user selects a color, store this color in self.bgcolor (which will
		# later be saved to .miragerc) and set this background color:
		z = widget.get_property('color')
		self.bgcolor = z
		self.usettings['bgcolor'] = {'r': z.red, 'g': z.green, 'b': z.blue}
		if not self.usettings['simple_bgcolor']:
			self.layout.modify_bg(gtk.STATE_NORMAL, self.bgcolor)
			self.slideshow_window.modify_bg(gtk.STATE_NORMAL, self.bgcolor)
			self.slideshow_window2.modify_bg(gtk.STATE_NORMAL, self.bgcolor)

	def simple_bgcolor_selected(self, widget):
		if widget.get_active():
			self.usettings['simple_bgcolor'] = True
			self.layout.modify_bg(gtk.STATE_NORMAL, None)
		else:
			self.usettings['simple_bgcolor'] = False
			self.bgcolor_selected(self.colorbutton)

	def show_about(self, action):
		# Help > About
		self.about_dialog = gtk.AboutDialog()
		try:
			self.about_dialog.set_transient_for(self.window)
			self.about_dialog.set_modal(True)
		except:
			pass
		self.about_dialog.set_name(__appname__)
		self.about_dialog.set_version(__version__)
		self.about_dialog.set_comments(_('A fast GTK+ Image Viewer.'))
		self.about_dialog.set_license(__license__)
		self.about_dialog.set_authors(['Scott Horowitz <stonecrest@gmail.com> (retired, original developer)', 'Fredric Johansson <fredric.miscmail@gmail.com>'])
		self.about_dialog.set_artists(['William Rea <sillywilly@gmail.com>'])
		self.about_dialog.set_translator_credits('cs - Petr Pisar <petr.pisar@atlas.cz>\nde - Bjoern Martensen <bjoern.martensen@gmail.com>\nes - Isidro Arribas <cdhotfire@gmail.com>\nfr - Mike Massonnet <mmassonnet@gmail.com>\nhu - Sandor Lisovszki <lisovszki@dunakanyar.net>\nnl - Pascal De Vuyst <pascal.devuyst@gmail.com>\npl - Tomasz Dominikowski <dominikowski@gmail.com>\npt_BR - Danilo Martins <mawkee@gmail.com>\nru - mavka <mavka@justos.org>\nit - Daniele Maggio <dado84@freemail.it>\nzh_CN - Jayden Suen <no.sun@163.com>')
		gtk.about_dialog_set_url_hook(self.show_website, "http://mirageiv.berlios.de")
		self.about_dialog.set_website_label("http://mirageiv.berlios.de")
		icon_path = self.find_path('mirage.png')
		try:
			icon_pixbuf = gtk.gdk.pixbuf_new_from_file(icon_path)
			self.about_dialog.set_logo(icon_pixbuf)
		except:
			pass
		self.about_dialog.connect('response', self.close_about)
		self.about_dialog.connect('delete_event', self.close_about)
		self.about_dialog.show_all()

	def show_website(self, dialog, blah, link):
		self.browser_load(link)

	def show_help(self, action):
		self.browser_load("http://mirageiv.berlios.de/docs.html")

	def browser_load(self, docslink):
		try:
			pid = subprocess.Popen(["xdg-open", docslink]).pid
		except:
			try:
				pid = subprocess.Popen(["gnome-open", docslink]).pid
			except:
				try:
					pid = subprocess.Popen(["exo-open", docslink]).pid
				except:
					try:
						pid = subprocess.Popen(["kfmclient", "openURL", docslink]).pid
					except:
						try:
							pid = subprocess.Popen(["firefox", docslink]).pid
						except:
							try:
								pid = subprocess.Popen(["mozilla", docslink]).pid
							except:
								try:
									pid = subprocess.Popen(["opera", docslink]).pid
								except:
									error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('Unable to launch a suitable browser.'))
									error_dialog.run()
									error_dialog.destroy()

	def close_about(self, event, data=None):
		self.about_dialog.hide()
		return True

	def mousewheel_scrolled(self, widget, event):
		if event.type == gtk.gdk.SCROLL:
			# Zooming of the image by Ctrl-mousewheel
			if event.state & gtk.gdk.CONTROL_MASK:
				if event.direction == gtk.gdk.SCROLL_UP:
					self.zoom_in(None)
				elif event.direction == gtk.gdk.SCROLL_DOWN:
					self.zoom_out(None)
				return True
			# Navigation of images with mousewheel:
			else:
				if event.direction == gtk.gdk.SCROLL_UP:
					self.goto_prev_image(None)
				elif event.direction == gtk.gdk.SCROLL_DOWN:
					self.goto_next_image(None)
				return True

	def mouse_moved(self, widget, event):
		# This handles the panning of the image
		if event.is_hint:
			x, y, state = event.window.get_pointer()
		else:
			state = event.state
		x, y = event.x_root, event.y_root
		if (state & gtk.gdk.BUTTON2_MASK) or (state & gtk.gdk.BUTTON1_MASK):
			# Prevent self.expose_event() from potentially further changing the
			# adjustments upon the adjustment value changes
			self.updating_adjustments = True
			xadjust = self.layout.get_hadjustment()
			newx = xadjust.value + (self.prevmousex - x)
			if newx >= xadjust.lower and newx <= xadjust.upper - xadjust.page_size:
				xadjust.set_value(newx)
				self.layout.set_hadjustment(xadjust)
			yadjust = self.layout.get_vadjustment()
			newy = yadjust.value + (self.prevmousey - y)
			if newy >= yadjust.lower and newy <= yadjust.upper - yadjust.page_size:
				yadjust.set_value(newy)
				self.layout.set_vadjustment(yadjust)
			self.updating_adjustments = False
		self.prevmousex = x
		self.prevmousey = y
		if self.fullscreen_mode:
			# Show cursor on movement, then hide after 2 seconds of no movement
			self.change_cursor(None)
			if not self.slideshow_controls_visible:
				gobject.source_remove(self.timer_id)
				if not self.closing_app:
					while gtk.events_pending():
						gtk.main_iteration()
				self.timer_id = gobject.timeout_add(2000, self.hide_cursor)
			(xpos, ypos) = self.window.get_position()
			if y - ypos > 0.9*self.available_image_height():
				self.slideshow_controls_show()
			else:
				self.slideshow_controls_hide()
		return True

	def button_pressed(self, widget, event):
		if self.image_loaded:
			# Double-click switch fullscreen:
			if event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS:
				self.enter_fullscreen(None)
			elif event.button == 2:
				if self.last_image_action_was_fit:
					self.zoom_1_to_1(None,False,False)
				else:
					self.zoom_to_fit_window(None, False, False)
			# Changes the cursor to the 'resize' cursor, like GIMP, on a middle click:
			elif event.button == 1 and (self.hscroll.get_property('visible')==True or self.vscroll.get_property('visible')==True):
				self.change_cursor(gtk.gdk.Cursor(gtk.gdk.FLEUR))
				self.prevmousex = event.x_root
				self.prevmousey = event.y_root
			# Right-click popup:
			elif self.image_loaded and event.button == 3:
				self.UIManager.get_widget('/Popup').popup(None, None, None, event.button, event.time)
		return True

	def button_released(self, widget, event):
		# Resets the cursor when middle mouse button is released
		if event.button == 2 or event.button == 1:
			self.change_cursor(None)
		return True

	def image_zoom_fit_update(self):
		if self.image_loaded and self.last_image_action_was_fit:
			if self.last_image_action_was_smart_fit:
				self.zoom_to_fit_or_1_to_1(None, False, False)
			else:
				self.zoom_to_fit_window(None, False, False)

	def zoom_in(self, action):
		if self.currimg.isloaded and self.UIManager.get_widget('/MainMenu/ViewMenu/In').get_property('sensitive'):
			self.image_zoomed = True
			wanted_zoomratio = self.currimg.zoomratio * 1.25
			self.set_zoom_sensitivities()
			self.last_image_action_was_fit = False
			self.put_zoom_image_to_window(False, wanted_zoomratio)
			self.update_statusbar()

	def reload(self, action):
		# First move the selected image to the top of the list so that
		# it will be automatically selected. The image list is always sorted so
		# the position of the image will not be changed because of this.
		img = self.image_list[self.curr_img_in_list]
		self.image_list.remove(img)
		self.image_list.insert(0, img)
		self.expand_filelist_and_load_image(list(self.image_list))

	def zoom_out(self, action):
		if self.currimg.isloaded and self.UIManager.get_widget('/MainMenu/ViewMenu/Out').get_property('sensitive'):
			if self.currimg.zoomratio == self.min_zoomratio:
				# No point in proceeding..
				return
			self.image_zoomed = True
			wanted_zoomratio = self.currimg.zoomratio * 1/1.25
			if wanted_zoomratio < self.min_zoomratio:
				wanted_zoomratio = self.min_zoomratio
			self.set_zoom_sensitivities()
			self.last_image_action_was_fit = False
			self.put_zoom_image_to_window(False, wanted_zoomratio)
			self.update_statusbar()

	def zoom_to_fit_window_action(self, action):
		self.zoom_to_fit_window(action, False, False)

	def calc_ratio(self, img, ):
		"""Calculate the ratio needed to fit the image in the view window"""
		win_width = self.available_image_width()
		win_height = self.available_image_height()
		preimg_width = img.width_original
		preimg_height = img.height_original
		prewidth_ratio = float(preimg_width)/win_width
		preheight_ratio = float(preimg_height)/win_height
		if prewidth_ratio < preheight_ratio:
			premax_ratio = preheight_ratio
		else:
			premax_ratio = prewidth_ratio
		return 1/float(premax_ratio)

	def zoom_to_fit_window(self, action, is_preloadimg_next, is_preloadimg_prev):
		if is_preloadimg_next:
			if self.usettings['preloading_images'] and self.nextimg.index != -1:
				self.nextimg.zoomratio = self.calc_ratio(self.nextimg)
		elif is_preloadimg_prev:
			if self.usettings['preloading_images'] and self.previmg.index != -1:
				self.previmg.zoomratio = self.calc_ratio(self.previmg)
		else:
			if self.currimg.isloaded and (self.slideshow_mode or self.UIManager.get_widget('/MainMenu/ViewMenu/Fit').get_property('sensitive')):
				self.image_zoomed = True
				self.usettings['last_mode'] = self.open_mode_fit
				self.last_image_action_was_fit = True
				self.last_image_action_was_smart_fit = False
				# Calculate zoomratio needed to fit to window:
				wanted_zoomratio = self.calc_ratio(self.currimg)
				self.set_zoom_sensitivities()
				self.put_zoom_image_to_window(False, wanted_zoomratio)
				self.update_statusbar()

	def zoom_to_fit_or_1_to_1(self, action, is_preloadimg_next, is_preloadimg_prev):
		if is_preloadimg_next:
			if self.usettings['preloading_images'] and self.nextimg.index != -1:
				self.nextimg.zoomratio = self.calc_ratio(self.nextimg)
				if self.nextimg.zoomratio > 1:
					self.nextimg.zoomratio = 1
		elif is_preloadimg_prev:
			if self.usettings['preloading_images'] and self.previmg.index != -1:
				self.previmg.zoomratio = self.calc_ratio(self.previmg)
				if self.previmg.zoomratio > 1:
					self.previmg.zoomratio = 1
		else:
			if self.currimg.isloaded:
				self.image_zoomed = True
				# Calculate zoomratio needed to fit to window:
				wanted_zoomratio = self.calc_ratio(self.currimg)
				self.set_zoom_sensitivities()
				if wanted_zoomratio > 1:
					# Revert to 1:1 zoom
					self.zoom_1_to_1(action, False, False)
				else:
					self.put_zoom_image_to_window(False, wanted_zoomratio)
					self.update_statusbar()
				self.last_image_action_was_fit = True
				self.last_image_action_was_smart_fit = True

	def zoom_1_to_1_action(self, action):
		self.zoom_1_to_1(action, False, False)

	def zoom_1_to_1(self, action, is_preloadimg_next, is_preloadimg_prev):
		if is_preloadimg_next:
			if self.usettings['preloading_images']:
				self.nextimg.zoomratio = 1
		elif is_preloadimg_prev:
			if self.usettings['preloading_images']:
				self.previmg.zoomratio = 1
		else:
			if self.currimg.isloaded and (self.slideshow_mode or self.currimg.animation or (not self.currimg.animation and self.UIManager.get_widget('/MainMenu/ViewMenu/1:1').get_property('sensitive'))):
				self.image_zoomed = True
				self.usettings['last_mode'] = self.open_mode_1to1
				self.last_image_action_was_fit = False
				wanted_zoomratio = 1
				self.put_zoom_image_to_window(False, wanted_zoomratio)
				self.update_statusbar()

	def zoom_check_and_execute(self,action, is_preloadimg_next, is_preloadimg_prev):
		if self.usettings['open_mode'] == self.open_mode_smart or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_smart):
			self.zoom_to_fit_or_1_to_1(action, is_preloadimg_next, is_preloadimg_prev)
		elif self.usettings['open_mode'] == self.open_mode_fit or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_fit):
			self.zoom_to_fit_window(action, is_preloadimg_next, is_preloadimg_prev)
		elif self.usettings['open_mode'] == self.open_mode_1to1 or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_1to1):
			self.zoom_1_to_1(action, is_preloadimg_next, is_preloadimg_prev)

	def rotate_left(self, action):
		self.rotate_left_or_right('/MainMenu/EditMenu/Rotate Left', 90)

	def rotate_right(self, action):
		self.rotate_left_or_right('/MainMenu/EditMenu/Rotate Right', 270)

	def rotate_left_or_right(self, widgetname, angle):
		if self.currimg.isloaded and self.UIManager.get_widget(widgetname).get_property('sensitive'):
			self.currimg.rotate_pixbuf(angle)
			if self.last_image_action_was_fit:
				if self.last_image_action_was_smart_fit:
					self.zoom_to_fit_or_1_to_1(None, False, False)
				else:
					self.zoom_to_fit_window(None, False, False)
			else:
				self.layout.set_size(self.currimg.width, self.currimg.height)
				self.imageview.set_from_pixbuf(self.currimg.pixbuf)
				self.show_scrollbars_if_needed()
				self.center_image()
				self.update_statusbar()
			self.image_modified = True

	def flip_image_vert(self, action):
		self.flip_image_vert_or_horiz(('/MainMenu/EditMenu/Flip Vertically'), True)

	def flip_image_horiz(self, action):
		self.flip_image_vert_or_horiz('/MainMenu/EditMenu/Flip Horizontally', False)

	def flip_image_vert_or_horiz(self, widgetname, vertical):
		if self.currimg.isloaded and self.UIManager.get_widget(widgetname).get_property('sensitive'):
			self.currimg.flip_pixbuf(vertical)
			self.imageview.set_from_pixbuf(self.currimg.pixbuf)
			self.image_modified = True

	def copy_to_clipboard(self, action):
		"""Copies the currently viewed image to the clipboard"""
		clipboard = gtk.Clipboard()
		clipboard.set_image(self.currimg.pixbuf)

	def get_pixbuf_of_size(self, pixbuf, size, zoom_quality):
		# Creates a pixbuf that fits in the specified square of sizexsize
		# while preserving the aspect ratio
		# Returns tuple: (scaled_pixbuf, actual_width, actual_height)
		image_width = pixbuf.get_width()
		image_height = pixbuf.get_height()
		if image_width-size > image_height-size:
			if image_width > size:
				image_height = int(size/float(image_width)*image_height)
				image_width = size
		else:
			if image_height > size:
				image_width = int(size/float(image_height)*image_width)
				image_height = size
		if pixbuf.get_has_alpha():
			colormap = self.imageview.get_colormap()
			light_grey = colormap.alloc_color('#666666', True, True)
			dark_grey = colormap.alloc_color('#999999', True, True)
			crop_pixbuf = pixbuf.composite_color_simple(image_width, image_height, zoom_quality, 255, 8, light_grey.pixel, dark_grey.pixel)
		else:
			crop_pixbuf = pixbuf.scale_simple(image_width, image_height, zoom_quality)
		return (crop_pixbuf, image_width, image_height)

	def pixbuf_add_border(self, pix):
		# Add a gray outline to pix. This will increase the pixbuf size by
		# 2 pixels lengthwise and heightwise, 1 on each side. Returns pixbuf.
		try:
			width = pix.get_width()
			height = pix.get_height()
			newpix = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, width+2, height+2)
			newpix.fill(0x858585ff)
			pix.copy_area(0, 0, width, height, newpix, 1, 1)
			return newpix
		except:
			return pix

	def crop_image(self, action):
		dialog = gtk.Dialog(_("Crop Image"), self.window, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		cropbutton = dialog.add_button(_("C_rop"), gtk.RESPONSE_ACCEPT)
		cropimage = gtk.Image()
		cropimage.set_from_stock(gtk.STOCK_OK, gtk.ICON_SIZE_BUTTON)
		cropbutton.set_image(cropimage)
		image = gtk.DrawingArea()
		crop_pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original, 400, self.zoom_quality)
		image.set_size_request(image_width, image_height)
		hbox = gtk.HBox()
		hbox.pack_start(gtk.Label(), expand=True)
		hbox.pack_start(image, expand=False)
		hbox.pack_start(gtk.Label(), expand=True)
		vbox_left = gtk.VBox()
		x_adj = gtk.Adjustment(0, 0, self.currimg.pixbuf_original.get_width(), 1, 10, 0)
		x = gtk.SpinButton(x_adj, 0, 0)
		x.set_numeric(True)
		x.set_update_policy(gtk.UPDATE_IF_VALID)
		x.set_wrap(False)
		x_label = gtk.Label("X:")
		x_label.set_alignment(0, 0.7)
		y_adj = gtk.Adjustment(0, 0, self.currimg.pixbuf_original.get_height(), 1, 10, 0)
		y = gtk.SpinButton(y_adj, 0, 0)
		y.set_numeric(True)
		y.set_update_policy(gtk.UPDATE_IF_VALID)
		y.set_wrap(False)
		y_label = gtk.Label("Y:")
		x_label.set_size_request(y_label.size_request()[0], -1)
		hbox_x = gtk.HBox()
		hbox_y = gtk.HBox()
		hbox_x.pack_start(x_label, False, False, 10)
		hbox_x.pack_start(x, False, False, 0)
		hbox_x.pack_start(gtk.Label(), False, False, 3)
		hbox_y.pack_start(y_label, False, False, 10)
		hbox_y.pack_start(y, False, False, 0)
		hbox_y.pack_start(gtk.Label(), False, False, 3)
		vbox_left.pack_start(hbox_x, False, False, 0)
		vbox_left.pack_start(hbox_y, False, False, 0)
		vbox_right = gtk.VBox()
		width_adj = gtk.Adjustment(self.currimg.pixbuf_original.get_width(), 1, self.currimg.pixbuf_original.get_width(), 1, 10, 0)
		width = gtk.SpinButton(width_adj, 0, 0)
		width.set_numeric(True)
		width.set_update_policy(gtk.UPDATE_IF_VALID)
		width.set_wrap(False)
		width_label = gtk.Label(_("Width:"))
		width_label.set_alignment(0, 0.7)
		height_adj = gtk.Adjustment(self.currimg.pixbuf_original.get_height(), 1, self.currimg.pixbuf_original.get_height(), 1, 10, 0)
		height = gtk.SpinButton(height_adj, 0, 0)
		height.set_numeric(True)
		height.set_update_policy(gtk.UPDATE_IF_VALID)
		height.set_wrap(False)
		height_label = gtk.Label(_("Height:"))
		width_label.set_size_request(height_label.size_request()[0], -1)
		height_label.set_alignment(0, 0.7)
		hbox_width = gtk.HBox()
		hbox_height = gtk.HBox()
		hbox_width.pack_start(width_label, False, False, 10)
		hbox_width.pack_start(width, False, False, 0)
		hbox_height.pack_start(height_label, False, False, 10)
		hbox_height.pack_start(height, False, False, 0)
		vbox_right.pack_start(hbox_width, False, False, 0)
		vbox_right.pack_start(hbox_height, False, False, 0)
		hbox2 = gtk.HBox()
		hbox2.pack_start(gtk.Label(), expand=True)
		hbox2.pack_start(vbox_left, False, False, 0)
		hbox2.pack_start(vbox_right, False, False, 0)
		hbox2.pack_start(gtk.Label(), expand=True)
		dialog.vbox.pack_start(hbox, False, False, 0)
		dialog.vbox.pack_start(hbox2, False, False, 15)
		dialog.set_resizable(False)
		dialog.vbox.show_all()
		image.set_events(gtk.gdk.POINTER_MOTION_MASK | gtk.gdk.POINTER_MOTION_HINT_MASK | gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_MOTION_MASK | gtk.gdk.BUTTON_RELEASE_MASK)
		image.connect("expose-event", self.crop_image_expose_cb, crop_pixbuf, image_width, image_height)
		image.connect("motion_notify_event", self.crop_image_mouse_moved, image, 0, 0, x, y, width, height, image_width, image_height, width_adj, height_adj)
		image.connect("button_press_event", self.crop_image_button_press, image)
		image.connect("button_release_event", self.crop_image_button_release)
		self.x_changed = x.connect('value-changed', self.crop_value_changed, x, y, width, height, width_adj, height_adj, image_width, image_height, image, 0)
		self.y_changed = y.connect('value-changed', self.crop_value_changed, x, y, width, height, width_adj, height_adj, image_width, image_height, image, 1)
		self.width_changed = width.connect('value-changed', self.crop_value_changed, x, y, width, height, width_adj, height_adj, image_width, image_height, image, 2)
		self.height_changed = height.connect('value-changed', self.crop_value_changed, x, y, width, height, width_adj, height_adj, image_width, image_height, image, 3)
		image.realize()
		self.crop_rectangle = [0, 0]
		self.drawing_crop_rectangle = False
		self.update_rectangle = False
		self.rect = None
		response = dialog.run()
		if response == gtk.RESPONSE_ACCEPT:
			dialog.destroy()
			if self.rect != None:
				self.currimg.crop(self.coords)
				gc.collect()
				self.put_zoom_image_to_window(False)
				# self.load_new_image2(False, True, False, False)
				self.image_modified = True
		else:
			dialog.destroy()

	def crop_value_changed(self, currspinbox, x, y, width, height, width_adj, height_adj, image_width, image_height, image, type):
		if type == 0:   # X
			if x.get_value() + width.get_value() > self.currimg.pixbuf_original.get_width():
				width.handler_block(self.width_changed)
				width.set_value(self.currimg.pixbuf_original.get_width() - x.get_value())
				width.handler_unblock(self.width_changed)
		elif type == 1: # Y
			if y.get_value() + height.get_value() > self.currimg.pixbuf_original.get_height():
				height.handler_block(self.height_changed)
				height.set_value(self.currimg.pixbuf_original.get_height() - y.get_value())
				height.handler_unblock(self.height_changed)
		self.coords = [int(x.get_value()), int(y.get_value()), int(width.get_value()), int(height.get_value())]
		self.crop_rectangle[0] = int(round(float(self.coords[0])/self.currimg.pixbuf_original.get_width()*image_width, 0))
		self.crop_rectangle[1] = int(round(float(self.coords[1])/self.currimg.pixbuf_original.get_height()*image_height, 0))
		x2 = int(round(float(self.coords[2])/self.currimg.pixbuf_original.get_width()*image_width, 0)) + self.crop_rectangle[0]
		y2 = int(round(float(self.coords[3])/self.currimg.pixbuf_original.get_height()*image_height, 0)) + self.crop_rectangle[1]
		self.drawing_crop_rectangle = True
		self.update_rectangle = True
		self.crop_image_mouse_moved(None, None, image, x2, y2, x, y, width, height, image_width, image_height, width_adj, height_adj)
		self.update_rectangle = False
		self.drawing_crop_rectangle = False

	def crop_image_expose_cb(self, image, event, pixbuf, width, height):
		image.window.draw_pixbuf(None, pixbuf, 0, 0, 0, 0, width, height)

	def crop_image_mouse_moved(self, widget, event, image, x2, y2, x, y, width, height, image_width, image_height, width_adj, height_adj):
		if event != None:
			x2, y2, state = event.window.get_pointer()
		if self.drawing_crop_rectangle:
			if self.crop_rectangle != None or self.update_rectangle:
				gc = image.window.new_gc(function=gtk.gdk.INVERT)
				if self.rect != None:
					# Get rid of the previous drawn rectangle:
					image.window.draw_rectangle(gc, False, self.rect[0], self.rect[1], self.rect[2], self.rect[3])
				self.rect = [0, 0, 0, 0]
				if self.crop_rectangle[0] > x2:
					self.rect[0] = x2
					self.rect[2] = self.crop_rectangle[0]-x2
				else:
					self.rect[0] = self.crop_rectangle[0]
					self.rect[2] = x2-self.crop_rectangle[0]
				if self.crop_rectangle[1] > y2:
					self.rect[1] = y2
					self.rect[3] = self.crop_rectangle[1]-y2
				else:
					self.rect[1] = self.crop_rectangle[1]
					self.rect[3] = y2-self.crop_rectangle[1]
				image.window.draw_rectangle(gc, False, self.rect[0], self.rect[1], self.rect[2], self.rect[3])
				# Convert the rectangle coordinates of the current image
				# to coordinates of pixbuf_original
				if self.rect[0] < 0:
					self.rect[2] = self.rect[2] + self.rect[0]
					self.rect[0] = 0
				if self.rect[1] < 0:
					self.rect[3] = self.rect[3] + self.rect[1]
					self.rect[1] = 0
				if event != None:
					self.coords = [0,0,0,0]
					self.coords[0] = int(round(float(self.rect[0])/image_width*self.currimg.pixbuf_original.get_width(), 0))
					self.coords[1] = int(round(float(self.rect[1])/image_height*self.currimg.pixbuf_original.get_height(), 0))
					self.coords[2] = int(round(float(self.rect[2])/image_width*self.currimg.pixbuf_original.get_width(), 0))
					self.coords[3] = int(round(float(self.rect[3])/image_height*self.currimg.pixbuf_original.get_height(), 0))
					if self.coords[0] + self.coords[2] > self.currimg.pixbuf_original.get_width():
						self.coords[2] = self.currimg.pixbuf_original.get_width() - self.coords[0]
					if self.coords[1] + self.coords[3] > self.currimg.pixbuf_original.get_height():
						self.coords[3] = self.currimg.pixbuf_original.get_height() - self.coords[1]
				x.handler_block(self.x_changed)
				y.handler_block(self.y_changed)
				width.handler_block(self.width_changed)
				height.handler_block(self.height_changed)
				x.set_value(self.coords[0])
				y.set_value(self.coords[1])
				width.set_value(self.coords[2])
				height.set_value(self.coords[3])
				x.handler_unblock(self.x_changed)
				y.handler_unblock(self.y_changed)
				width_adj.set_property('upper', self.currimg.pixbuf_original.get_width() - self.coords[0])
				height_adj.set_property('upper', self.currimg.pixbuf_original.get_height() - self.coords[1])
				width.handler_unblock(self.width_changed)
				height.handler_unblock(self.height_changed)

	def crop_image_button_press(self, widget, event, image):
		x, y, state = event.window.get_pointer()
		if (state & gtk.gdk.BUTTON1_MASK):
			self.drawing_crop_rectangle = True
			self.crop_rectangle = [x, y]
			gc = image.window.new_gc(function=gtk.gdk.INVERT)
			if self.rect != None:
				# Get rid of the previous drawn rectangle:
				image.window.draw_rectangle(gc, False, self.rect[0], self.rect[1], self.rect[2], self.rect[3])
				self.rect = None

	def crop_image_button_release(self, widget, event):
		x, y, state = event.window.get_pointer()
		if not (state & gtk.gdk.BUTTON1_MASK):
			self.drawing_crop_rectangle = False

	def saturation(self, action):
		dialog = gtk.Dialog(_("Saturation"), self.window, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		resizebutton = dialog.add_button(_("_Saturate"), gtk.RESPONSE_ACCEPT)
		resizeimage = gtk.Image()
		resizeimage.set_from_stock(gtk.STOCK_OK, gtk.ICON_SIZE_BUTTON)
		resizebutton.set_image(resizeimage)
		scale = gtk.HScale()
		scale.set_draw_value(False)
		scale.set_update_policy(gtk.UPDATE_DISCONTINUOUS)
		scale.set_range(0, 2)
		scale.set_increments(0.1, 0.5)
		scale.set_value(1)
		scale.connect('value-changed', self.saturation_preview)
		label = gtk.Label(_("Saturation level:"))
		label.set_alignment(0, 0.5)
		hbox1 = gtk.HBox()
		hbox1.pack_start(label, True, True, 10)
		hbox2 = gtk.HBox()
		hbox2.pack_start(scale, True, True, 20)
		dialog.vbox.pack_start(gtk.Label(" "))
		dialog.vbox.pack_start(hbox1, False)
		dialog.vbox.pack_start(hbox2, True, True, 10)
		dialog.vbox.pack_start(gtk.Label(" "))
		dialog.set_default_response(gtk.RESPONSE_ACCEPT)
		dialog.vbox.show_all()
		response = dialog.run()
		if response == gtk.RESPONSE_ACCEPT:
			self.currimg.saturation(scale.get_value())
			self.imageview.set_from_pixbuf(self.currimg.pixbuf)
			self.image_modified = True
			dialog.destroy()
		else:
			self.imageview.set_from_pixbuf(self.currimg.pixbuf)
			dialog.destroy()

	def saturation_preview(self, range):
		while gtk.events_pending():
			gtk.main_iteration()
		try:
			bak = self.currimg.pixbuf.copy()
			self.currimg.pixbuf.saturate_and_pixelate(self.currimg.pixbuf, range.get_value(), False)
			self.imageview.set_from_pixbuf(self.currimg.pixbuf)
			self.currimg.pixbuf = bak.copy()
			del bak
		except:
			pass
		gc.collect()

	def resize_image(self, action):
		dialog = gtk.Dialog(_("Resize Image"), self.window, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		resizebutton = dialog.add_button(_("_Resize"), gtk.RESPONSE_ACCEPT)
		resizeimage = gtk.Image()
		resizeimage.set_from_stock(gtk.STOCK_OK, gtk.ICON_SIZE_BUTTON)
		resizebutton.set_image(resizeimage)
		hbox_width = gtk.HBox()
		width_adj = gtk.Adjustment(self.currimg.pixbuf_original.get_width(), 1, 100000000000, 1, 10, 0)
		width = gtk.SpinButton(width_adj, 0, 0)
		width.set_numeric(True)
		width.set_update_policy(gtk.UPDATE_IF_VALID)
		width.set_wrap(False)
		width_label = gtk.Label(_("Width:"))
		width_label.set_alignment(0, 0.7)
		hbox_width.pack_start(width_label, False, False, 10)
		hbox_width.pack_start(width, False, False, 0)
		hbox_width.pack_start(gtk.Label(_("pixels")), False, False, 10)
		hbox_height = gtk.HBox()
		height_adj = gtk.Adjustment(self.currimg.pixbuf_original.get_height(), 1, 100000000000, 1, 10, 0)
		height = gtk.SpinButton(height_adj, 0, 0)
		height.set_numeric(True)
		height.set_update_policy(gtk.UPDATE_IF_VALID)
		height.set_wrap(False)
		height_label = gtk.Label(_("Height:"))
		width_label.set_size_request(height_label.size_request()[0], -1)
		height_label.set_alignment(0, 0.7)
		hbox_height.pack_start(height_label, False, False, 10)
		hbox_height.pack_start(height, False, False, 0)
		hbox_height.pack_start(gtk.Label(_("pixels")), False, False, 10)
		hbox_aspect = gtk.HBox()
		aspect_checkbox = gtk.CheckButton(_("Preserve aspect ratio"))
		aspect_checkbox.set_active(self.preserve_aspect)
		hbox_aspect.pack_start(aspect_checkbox, False, False, 10)
		vbox = gtk.VBox()
		vbox.pack_start(gtk.Label(), False, False, 0)
		vbox.pack_start(hbox_width, False, False, 0)
		vbox.pack_start(hbox_height, False, False, 0)
		vbox.pack_start(gtk.Label(), False, False, 0)
		vbox.pack_start(hbox_aspect, False, False, 0)
		vbox.pack_start(gtk.Label(), False, False, 0)
		hbox_total = gtk.HBox()
		if self.currimg.animation:
			pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original.get_static_image(), 96, self.zoom_quality)
		else:
			pixbuf, image_width, image_height = self.get_pixbuf_of_size(self.currimg.pixbuf_original, 96, self.zoom_quality)
		image = gtk.Image()
		image.set_from_pixbuf(self.pixbuf_add_border(pixbuf))
		hbox_total.pack_start(image, False, False, 10)
		hbox_total.pack_start(vbox, False, False, 10)
		dialog.vbox.pack_start(hbox_total, False, False, 0)
		width.connect('value-changed', self.preserve_image_aspect, "width", height)
		height.connect('value-changed', self.preserve_image_aspect, "height", width)
		aspect_checkbox.connect('toggled', self.aspect_ratio_toggled, width, height)
		dialog.set_default_response(gtk.RESPONSE_ACCEPT)
		dialog.vbox.show_all()
		response = dialog.run()
		if response == gtk.RESPONSE_ACCEPT:
			pixelheight = height.get_value_as_int()
			pixelwidth = width.get_value_as_int()
			dialog.destroy()
			self.currimg.resize(pixelwidth, pixelheight, self.zoom_quality)
			self.put_zoom_image_to_window(False)
			# self.load_new_image2(False, True, False, False)
			self.image_modified = True
		else:
			dialog.destroy()

	def aspect_ratio_toggled(self, togglebutton, width, height):
		self.preserve_aspect = togglebutton.get_active()
		if self.preserve_aspect:
			# Set height based on width and aspect ratio
			target_value = float(width.get_value_as_int())/self.currimg.pixbuf_original.get_width()
			target_value = int(target_value * self.currimg.pixbuf_original.get_height())
			self.ignore_preserve_aspect_callback = True
			height.set_value(target_value)
			self.ignore_preserve_aspect_callback = False

	def preserve_image_aspect(self, currspinbox, type, otherspinbox):
		if not self.preserve_aspect:
			return
		if self.ignore_preserve_aspect_callback:
			return
		if type == "width":
			target_value = float(currspinbox.get_value_as_int())/self.currimg.pixbuf_original.get_width()
			target_value = int(target_value * self.currimg.pixbuf_original.get_height())
		else:
			target_value = float(currspinbox.get_value_as_int())/self.currimg.pixbuf_original.get_height()
			target_value = int(target_value * self.currimg.pixbuf_original.get_width())
		self.ignore_preserve_aspect_callback = True
		otherspinbox.set_value(target_value)
		self.ignore_preserve_aspect_callback = False

	def goto_prev_image(self, action):
		self.goto_image("PREV", action)

	def goto_next_image(self, action, through_timeout=False):
		self.goto_image("NEXT", action, through_timeout)

	def goto_random_image(self, action, through_timeout=False):
		self.goto_image("RANDOM", action, through_timeout)

	def goto_first_image(self, action):
		self.goto_image("FIRST", action)

	def goto_last_image(self, action):
		self.goto_image("LAST", action)

	def goto_first_image_prev_subfolder(self, action):
		self.goto_image("PREV_SUBFOLDER", action)

	def goto_first_image_next_subfolder(self, action):
		self.goto_image("NEXT_SUBFOLDER", action)

	def goto_image(self, location, action, called_by_timeout=False):
		"""Goes to the image specified by location. Location can be "LAST",
			"FIRST", "NEXT", "PREV", "RANDOM", or a number. If  at last image
			and "NEXT" is issued, it will wrap around or not depending on
			self.usettings['listwrap_mode']. Same action is made for first image
			and "PREV". """
		if self.slideshow_mode and action != "ss":
			gobject.source_remove(self.timer_delay)
		if ((location=="PREV" or location=="NEXT" or location=="RANDOM")\
				and len(self.image_list) > 1) or ((location == "PREV_SUBFOLDER" \
				or location == "NEXT_SUBFOLDER") and len(self.firstimgindex_subfolders_list) >= 2)\
				or (location=="FIRST" and (len(self.image_list) > 1 \
				and self.curr_img_in_list != 0)) or (location=="LAST"\
				and (len(self.image_list) > 1 and self.curr_img_in_list != len(self.image_list)-1))\
				or valid_int(location):
			self.load_new_image_stop_now()
			cancel = self.autosave_image()
			if cancel:
				return
			check_wrap = False
			prev_img = self.curr_img_in_list
			if location != "RANDOM":
				self.randomlist = []
				self.random_image_list = []
				self.current_random = -9
			if location == "FIRST":
				self.curr_img_in_list = 0
			elif location == "RANDOM":
				if self.randomlist == []:
					self.reinitialize_randomlist()
				else:
					# check if we have seen every image; if so, reinitialize array and repeat:
					if all(self.randomlist):
						check_wrap = True
			elif location == "LAST":
				self.curr_img_in_list = len(self.image_list)-1
			elif location == "PREV":
				if self.curr_img_in_list > 0:
					self.curr_img_in_list -= 1
				else:
					check_wrap = True
			elif location == "NEXT":
				if self.curr_img_in_list < len(self.image_list) - 1:
					self.curr_img_in_list += 1
				else:
					check_wrap = True
			elif location == "PREV_SUBFOLDER":
				if self.curr_img_in_list >= self.firstimgindex_subfolders_list[1]: #not in first subfolder
					self.curr_img_in_list = self.get_firstimgindex_curr_next_prev_subfolder(self.curr_img_in_list)[-1]
				else: #in first subfolder
					check_wrap = True
			elif location == "NEXT_SUBFOLDER":
				if self.curr_img_in_list < self.firstimgindex_subfolders_list[-1]: #not in last subfolder
					self.curr_img_in_list = self.get_firstimgindex_curr_next_prev_subfolder(self.curr_img_in_list)[1]
				else: #in last subfolder
					check_wrap = True
			if check_wrap: #we are at the beginning or end of the list or all images have been viewed in random mode
				if self.usettings['listwrap_mode'] == 0:
					if self.slideshow_mode and ((action == "ss" and (location == "NEXT" or location == "RANDOM")) or (action != "ss" and location == "NEXT")): #automatic next/random action or manual next action, stop slideshow
						self.toggle_slideshow(None)
						return
					elif self.slideshow_mode and action != "ss" and location == "PREV": #manual prev action, keep slideshow going
						pass
					elif not self.slideshow_mode and action != "ss" and (location == "PREV" or location == "NEXT"): #manual prev/next action, ignore as if not pressed
						return
					elif not self.slideshow_mode and action != "ss" and location == "RANDOM": #always next random image when pressing 'R'
						self.reinitialize_randomlist()
				elif self.usettings['listwrap_mode'] == 1:
					if location == "PREV":
						self.curr_img_in_list = len(self.image_list) - 1
					elif location == "NEXT" or location == "NEXT_SUBFOLDER":
						self.curr_img_in_list = 0
					elif location == "PREV_SUBFOLDER":
						self.curr_img_in_list = self.firstimgindex_subfolders_list[-1]
					elif location == "RANDOM": #always next random image
						self.reinitialize_randomlist()
					if (location == "PREV" or location == "NEXT") and self.going_random:
						self.randomize_list
						self.thumblist.clear()
						self.thumbpane_update_images(True, self.curr_img_in_list)
				elif self.usettings['listwrap_mode'] == 2:
					if self.curr_img_in_list != self.loaded_img_in_list:
						# Ensure that the user is looking at the correct "last" image before
						# they are asked the wrap question:
						if location == "PREV":
							self.load_new_image(True, False, True, True, True, True)
						else:
							self.load_new_image(False, False, True, True, True, True)
						self.set_go_navigation_sensitivities(False)
						self.thumbpane_select(self.curr_img_in_list)
					if self.fullscreen_mode:
						self.change_cursor(None)
					if location == "PREV":
						dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("You are viewing the first image in the list. Wrap around to the last image?"))
					elif location == "NEXT":
						dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("You are viewing the last image in the list. Wrap around to the first image?"))
					elif location == "PREV_SUBFOLDER":
						dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("You are viewing the first folder in the list. Wrap around to the first image of the last folder?"))
					elif location == "NEXT_SUBFOLDER":
						dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("You are viewing the last folder in the list. Wrap around to the first image of the first folder?"))
					elif location == "RANDOM":
						dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("All images have been viewed. Would you like to cycle through the images again?"))
					dialog.set_title(_("Wrap?"))
					dialog.label.set_property('can-focus', False)
					dialog.set_default_response(gtk.RESPONSE_YES)
					# Wrapping dialog.run() and .destroy() in .threads_enter()/leave() to prevent a hangup on linux
					# Could also be done with 'with gtk.gdk.lock:' but that doesn't work on windows.
					try:
						if called_by_timeout:
							gtk.gdk.threads_enter()
						self.user_prompt_visible = True
						response = dialog.run()
						dialog.destroy()
					except:
						response = None
					finally:
						if called_by_timeout:
							gtk.gdk.threads_leave()
						self.user_prompt_visible = False
					if response == gtk.RESPONSE_YES:
						print "WE got something"
						if location == "PREV":
							self.curr_img_in_list = len(self.image_list)-1
						elif location == "NEXT" or location == "NEXT_SUBFOLDER":
							self.curr_img_in_list = 0
						elif location == "PREV_SUBFOLDER":
							self.curr_img_in_list = self.firstimgindex_subfolders_list[-1]
						elif location == "RANDOM":
							self.reinitialize_randomlist()
						if (location == "PREV" or location == "NEXT") and self.going_random:
							self.randomize_list()
							self.thumblist.clear()
							self.thumbpane_update_images(True, self.curr_img_in_list)
						if self.fullscreen_mode:
							self.hide_cursor
					else:
						if self.fullscreen_mode:
							self.hide_cursor
						else:
							self.change_cursor(None)
						if self.slideshow_mode and action != "ss" and location == "PREV": #manual prev action, keep slideshow going
							pass
						elif self.slideshow_mode and ((action == "ss" and (location == "NEXT" or location == "RANDOM")) or (action != "ss" and location == "NEXT")): #automatic next/random action or manual next action, stop slideshow
							self.toggle_slideshow(None)
							return
						elif not self.slideshow_mode and action != "ss" and (location == "PREV" or location == "NEXT" or location == "RANDOM"): #manual prev/next/random action, ignore as if not pressed
							return
			if location == "RANDOM":
				# Find random image that hasn't already been chosen:
				j = random.randint(0, len(self.image_list)-1)
				difflength = len(self.randomlist) - len(self.image_list)
				if difflength > 0:
					self.randomlist.extend([False]*difflength)
				if self.randomlist[j]:
					not_viewed = [idx for idx,val in enumerate(self.randomlist) if not val]
					j = random.choice(not_viewed)
				self.curr_img_in_list = j
				self.randomlist[j] = True
				self.currimg.name = str(self.image_list[self.curr_img_in_list])
			if valid_int(location):
				self.curr_img_in_list = int(location)
			if self.curr_img_in_list != prev_img: #don't load the same image again if already loaded
				if not self.fullscreen_mode and (not self.slideshow_mode or (self.slideshow_mode and action != "ss")):
					self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
				if location == "PREV" or (valid_int(location) and int(location) == prev_img-1):
					self.load_when_idle = gobject.idle_add(self.load_new_image, True, False, True, True, True, True)
				else:
					self.load_when_idle = gobject.idle_add(self.load_new_image, False, False, True, True, True, True)
				self.set_go_navigation_sensitivities(False)
			if self.slideshow_mode:
				#if self.curr_slideshow_random:
				#	self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_random_image, "ss",True)
				#else:
					self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_next_image, "ss", True)
			gobject.idle_add(self.thumbpane_select, self.curr_img_in_list)

	def set_go_navigation_sensitivities(self, skip_initial_check):
		# setting skip_image_list_check to True is useful when calling from
		# expand_filelist_and_load_image() for example, as self.image_list has not
		# yet fully populated
		if (not self.image_loaded or len(self.image_list) == 1) and not skip_initial_check:
			self.set_common_image_sensitivities(False)
			self.set_previous_subfolder_sensitivities(False)
			self.set_next_subfolder_sensitivities(False)
		elif self.curr_img_in_list == 0:
			if self.usettings['listwrap_mode'] == 0:
				self.set_previous_image_sensitivities(False)
				self.set_previous_subfolder_sensitivities(False)
			else:
				self.set_previous_image_sensitivities(True)
				if len(self.firstimgindex_subfolders_list) >= 2: #subfolders
					self.set_previous_subfolder_sensitivities(True)
				else: #no subfolders
					self.set_previous_subfolder_sensitivities(False)
			self.set_first_image_sensitivities(False)
			self.set_next_image_sensitivities(True)
			self.set_last_image_sensitivities(True)
			self.set_random_image_sensitivities(True)
			if len(self.firstimgindex_subfolders_list) >= 2: #subfolders
				self.set_next_subfolder_sensitivities(True)
			else: #no subfolders
				self.set_next_subfolder_sensitivities(False)
		elif self.curr_img_in_list == len(self.image_list)-1:
			self.set_previous_image_sensitivities(True)
			self.set_first_image_sensitivities(True)
			if self.usettings['listwrap_mode'] == 0:
				self.set_next_image_sensitivities(False)
				self.set_next_subfolder_sensitivities(False)
			else:
				self.set_next_image_sensitivities(True)
				if len(self.firstimgindex_subfolders_list) >= 2: #subfolders
					self.set_next_subfolder_sensitivities(True)
				else: #no subfolders
					self.set_next_subfolder_sensitivities(False)
			self.set_last_image_sensitivities(False)
			self.set_random_image_sensitivities(True)
		elif len(self.firstimgindex_subfolders_list) >= 2 and self.curr_img_in_list < self.firstimgindex_subfolders_list[1]: #first subfolder
			self.set_common_image_sensitivities(True)
			if self.usettings['listwrap_mode'] == 0:
				self.set_previous_subfolder_sensitivities(False)
			else:
				self.set_previous_subfolder_sensitivities(True)
			self.set_next_subfolder_sensitivities(True)
		elif len(self.firstimgindex_subfolders_list) >= 2 and self.curr_img_in_list >= self.firstimgindex_subfolders_list[-1]: #last subfolder
			self.set_common_image_sensitivities(True)
			self.set_previous_subfolder_sensitivities(True)
			if self.usettings['listwrap_mode'] == 0:
				self.set_next_subfolder_sensitivities(False)
			else:
				self.set_next_subfolder_sensitivities(True)
		else: #inbetween first and last image/subfolder
			self.set_common_image_sensitivities(True)
			if len(self.firstimgindex_subfolders_list) >= 2: #subfolders
				self.set_previous_subfolder_sensitivities(True)
				self.set_next_subfolder_sensitivities(True)
			else: #no subfolders
				self.set_previous_subfolder_sensitivities(False)
				self.set_next_subfolder_sensitivities(False)

	def set_common_image_sensitivities(self, enable):
		self.set_previous_image_sensitivities(enable)
		self.set_first_image_sensitivities(enable)
		self.set_next_image_sensitivities(enable)
		self.set_last_image_sensitivities(enable)
		self.set_random_image_sensitivities(enable)

	def reinitialize_randomlist(self):
		self.randomlist = [False]*len(self.image_list)
		self.randomlist[self.curr_img_in_list] = True

	def shall_we_randomize(self,action):
		if self.UIManager.get_widget('/MainMenu/GoMenu/Randomize list').get_active():

			self.going_random = True
			if len(self.image_list) > 0:
				self.randomize_list()
				self.thumblist.clear()
				self.curr_img_in_list = self.image_list.index(self.currimg.name)
				self.thumbpane_update_images(True, self.curr_img_in_list)
				self.currimg.index = self.curr_img_in_list
				self.update_title()
		else:
			self.going_random = False

	def randomize_list(self):
		random.shuffle(self.image_list)
		self.previmg.unload_pixbuf()
		self.nextimg.unload_pixbuf()

	def image_load_failed(self, reset_cursor, filename=""):
		# If a filename is provided, use it for display:
		if len(filename) == 0:
			self.currimg.name = str(self.image_list[self.curr_img_in_list])
		else:
			self.currimg_name = filename
		if self.verbose and self.currimg.isloaded:
			print _("Loading: %s") % self.currimg.name
		self.update_title()
		self.put_error_image_to_window()
		self.image_loaded = False
		self.currimg.unload_pixbuf()
		if reset_cursor:
			if not self.fullscreen_mode:
				self.change_cursor(None)

	def load_new_image_stop_now(self):
		try:
			gobject.source_remove(self.load_when_idle)
		except:
			pass
		try:
			gobject.source_remove(self.preload_when_idle)
		except:
			pass
		try:
			gobject.source_remove(self.preload_when_idle2)
		except:
			pass

	def load_new_image(self, check_prev_last, use_current_pixbuf_original, reset_cursor, perform_onload_action, preload_next_image_after, preload_prev_image_after):
		try:
			self.load_new_image2(check_prev_last, use_current_pixbuf_original, reset_cursor, perform_onload_action)
		except:
			self.image_load_failed(True)
		if preload_next_image_after:
			self.preload_when_idle = gobject.idle_add(self.preload_next_image, False)
		if preload_prev_image_after:
			self.preload_when_idle2 = gobject.idle_add(self.preload_prev_image, False)

	def load_new_image2(self, check_prev_last, use_current_pixbuf_original, reset_cursor, perform_onload_action, skip_recentfiles=False, image_name=""):
		# check_prev_last is used to determine if we should check whether
		# preloadimg_prev can be reused last. This should really only
		# be done if the user just clicked the previous image button in
		# order to reduce the number of image loads.
		# If use_current_pixbuf_original == True, do not reload the
		# self.currimg.pixbuf_original from the file; instead, use the existing
		# one. This is only currently useful for resizing images.
		# Determine the indices in the self.image_list array for the
		# previous and next preload images.
		next_index = self.curr_img_in_list + 1
		if next_index > len(self.image_list)-1:
			if self.usettings['listwrap_mode'] == 0:
				next_index = -1
			else:
				next_index = 0
		prev_index = self.curr_img_in_list - 1
		if prev_index < 0:
			if self.usettings['listwrap_mode'] == 0:
				prev_index = -1
			else:
				prev_index = len(self.image_list)-1
		used_prev = False
		used_next = False
		if self.usettings['preloading_images']:
			if self.curr_img_in_list != self.loaded_img_in_list:
				if self.curr_img_in_list == self.previmg.index:
					#Can Copy previmg into currimg
					if self.loaded_img_in_list == next_index:
						self.nextimg = copy.copy(self.currimg)
						self.currimg = copy.copy(self.previmg)
					else:
						self.currimg = copy.copy(self.previmg)
					self.previmg.unload_pixbuf()
					used_prev = True
				elif self.curr_img_in_list == self.nextimg.index:
					#Can Copy nextimg into currimg
					if self.loaded_img_in_list == prev_index:
						self.previmg = copy.copy(self.currimg)
						self.currimg = copy.copy(self.nextimg)
					else:
						self.currimg = copy.copy(self.nextimg)
					self.nextimg.unload_pixbuf()
					used_next = True
				else:
					if self.previmg.index == next_index:
						self.nextimg = self.previmg
						self.previmg.unload_pixbuf()
					elif self.nextimg.index == prev_index:
						self.previmg = self.nextimg
						self.nextimg.unload_pixbuf()

		if used_prev or used_next:
			if self.verbose and self.currimg.name != "":
				print _("Loading(preloaded): %s") % self.currimg.name
			self.put_zoom_image_to_window(True)
			if not self.currimg.animation:
				self.set_image_sensitivities(True)
			else:
				self.set_image_sensitivities(False)
			# If we used a preload image, set the correct boolean variables
			if self.usettings['open_mode'] == self.open_mode_smart or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_smart):
				self.last_image_action_was_fit = True
				self.last_image_action_was_smart_fit = True
			elif self.usettings['open_mode'] == self.open_mode_fit or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_fit):
				self.last_image_action_was_fit = True
				self.last_image_action_was_smart_fit = False
			elif self.usettings['open_mode'] == self.open_mode_1to1 or (self.usettings['open_mode'] == self.open_mode_last and self.usettings['last_mode'] == self.open_mode_1to1):
				self.last_image_action_was_fit = False
		else:
			# Need to load the current image
			self.currimg.unload_pixbuf()
			if image_name == "":
				if len(self.image_list) == 1:
					image_name = str(self.image_list[0])
				else:
					image_name = str(self.image_list[self.curr_img_in_list])
			if self.verbose and image_name != "":
				print _("Loading(not preloaded): %s") % image_name
			if self.curr_img_in_list:
				self.currimg.load_pixbuf(image_name, self.curr_img_in_list)
			else:
				self.currimg.load_pixbuf(image_name)
			if self.currimg.animation:
				self.zoom_1_to_1(None, False, False)
				self.set_image_sensitivities(False)
			else:
				self.zoom_check_and_execute(None, False, False)
				self.set_image_sensitivities(True)
		if self.onload_cmd != None and perform_onload_action:
			self.parse_action_command(self.onload_cmd, False)
		self.update_statusbar()
		self.update_title()
		self.image_loaded = True
		self.image_modified = False
		self.image_zoomed = False
		self.set_slideshow_sensitivities()
		#if not skip_recentfiles:
		#	self.register_file_with_recent_docs(self.currimg.name)
		if reset_cursor:
			if not self.fullscreen_mode:
				self.change_cursor(None)

	def preload_next_image(self, use_existing_image):
		try:
			if self.usettings['preloading_images'] and len(self.image_list) > 1:
				if not use_existing_image:
					next_index = self.curr_img_in_list + 1
					if next_index > len(self.image_list)-1:
						if self.usettings['listwrap_mode'] == 0:
							self.nextimg.unload_pixbuf()
							return
						else:
							next_index = 0
					if next_index == self.nextimg.index:
						return
					name = str(self.image_list[next_index])
					self.nextimg.load_pixbuf(name, next_index)
				if self.nextimg.index == -1:
					return
				# Determine self.nextimg.zoomratio
				self.zoom_check_and_execute(None, True, False)
				# Zoom pixbuf
				colormap = self.imageview.get_colormap()
				self.nextimg.zoom_pixbuf(self.nextimg.zoomratio, self.zoom_quality, colormap)
				gc.collect()
				if self.verbose:
					print _("Preloading: %s") % self.nextimg.name
		except Exception as e:
			print (e)
			self.nextimg.unload_pixbuf()

	def preload_prev_image(self, use_existing_image):
		try:
			if self.usettings['preloading_images'] and len(self.image_list) > 1:
				if not use_existing_image:
					index = self.curr_img_in_list - 1
					if index < 0:
						if self.usettings['listwrap_mode'] == 0:
							self.previmg.unload_pixbuf()
							return
						else:
							prev_index = len(self.image_list)-1
					if index == self.previmg.index:
						return
					name = str(self.image_list[index])
					self.previmg.load_pixbuf(name, index)
				if self.previmg.index == -1:
					return
				# Determine self.previmg.zoomratio
				self.zoom_check_and_execute(None, False, True)
				# Always start with the original image to preserve quality!
				colormap = self.imageview.get_colormap()
				self.previmg.zoom_pixbuf(self.previmg.zoomratio, self.zoom_quality, colormap)
				gc.collect()
				if self.verbose:
					print _("Preloading: %s") % self.previmg.name
		except Exception as e:
			print(e)
			self.previmg.unload_pixbuf()

	def change_cursor(self, type):
		for i in gtk.gdk.window_get_toplevels():
			if i.get_window_type() != gtk.gdk.WINDOW_TEMP and i.get_window_type() != gtk.gdk.WINDOW_CHILD:
				i.set_cursor(type)
		self.layout.window.set_cursor(type)

	def expand_filelist_and_load_image(self, inputlist):
		# Takes the current list (i.e. ["pic.jpg", "pic2.gif", "../images"]) and
		# expands it into a list of all pictures found
		self.thumblist.clear()
		self.images_found = 0
		self.stop_now = True # Make sure that any previous search process is stopped
		self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		# Reset preload images:
		self.nextimg.unload_pixbuf()
		self.previmg.unload_pixbuf()
		# If any directories were passed, display "Searching..." in statusbar:
		self.searching_for_images = False
		for item in inputlist:
			if os.path.isdir(item):
				self.searching_for_images = True
				self.update_statusbar()
		if not self.closing_app:
			while gtk.events_pending():
				gtk.main_iteration()
		first_image = ""
		first_image_found = False
		first_image_loaded = False
		first_image_loaded_successfully = False
		self.previmg.unload_pixbuf()
		self.nextimg.unload_pixbuf()
		second_image = ""
		second_image_found = False
		second_image_preloaded = False
		self.randomlist = []
		folderlist = []
		self.image_list = []
		self.curr_img_in_list = -2
		go_buttons_enabled = False
		self.set_go_sensitivities(False)
		# Clean up list (remove preceding "file://" or "file:" and trailing "/")
		for itemnum in range(len(inputlist)):
			# Strip off preceding file..
			if inputlist[itemnum].startswith('file://'):
				inputlist[itemnum] = inputlist[itemnum][7:].decode('utf-8')
			elif inputlist[itemnum].startswith('file:'):
				inputlist[itemnum] = inputlist[itemnum][5:].decode('utf-8')
			# Strip off trailing "/" if it exists:
			if inputlist[itemnum][len(inputlist[itemnum])-1] == "/":
				inputlist[itemnum] = inputlist[itemnum][:(len(inputlist[itemnum])-1)]
			if not (inputlist[itemnum].startswith('http://') or inputlist[itemnum].startswith('ftp://')):
				inputlist[itemnum] = os.path.abspath(inputlist[itemnum])
			else:
				try:
					# Remote file. Save as /tmp/mirage-<random>/filename.ext
					tmpdir = tempfile.mkdtemp(prefix="mirage-") + "/"
					tmpfile = tmpdir + os.path.basename(inputlist[itemnum])
					socket.setdefaulttimeout(5)
					urllib.urlretrieve(inputlist[itemnum], tmpfile)
					inputlist[itemnum] = tmpfile.decode('utf-8')
				except:
					pass
		# Remove hidden files from list:
		if not self.usettings['open_hidden_files']:
			tmplist = []
			for item in inputlist:
				if os.path.basename(item)[0] != '.':
					tmplist.append(item)
				elif self.verbose:
					print _("Skipping: %s") % item
			inputlist = tmplist
			if len(inputlist) == 0:
				# All files/dirs were hidden, exit..
				self.currimg.unload_pixbuf()
				self.searching_for_images = False
				self.set_go_navigation_sensitivities(False)
				self.set_slideshow_sensitivities()
				if not self.closing_app:
					self.change_cursor(None)
				self.recursive = False
				self.put_error_image_to_window()
				self.update_title()
				return
		init_image = os.path.abspath(inputlist[0])
		if self.valid_image(init_image):
			try:
				self.load_new_image2(False, False, True, True, image_name=init_image)
				# Calling load_new_image2 will reset the following two vars
				# to 0, so ensure they are -1 again (no images preloaded)
				self.previmg.unload_pixbuf()
				self.nextimg.unload_pixbuf()
				if not self.currimg.animation:
					self.previmg_width = self.currimg.width
				else:
					self.previmg_width = self.currimg.width
				self.image_loaded = True
				first_image_loaded_successfully = True
				first_image_loaded = True
				print "Quickloaded image ahead of imagelist"
				if not self.closing_app:
					while gtk.events_pending():
						gtk.main_iteration(True)
			except:
				pass

		self.stop_now = False
		# If open all images in dir...
		if self.usettings['open_all_images']:
			temp = inputlist
			inputlist = []
			for item in temp:
				if os.path.isfile(item):
					itempath = os.path.dirname(os.path.abspath(item))
					temp = self.recursive
					self.recursive = False
					self.stop_now = False
					self.expand_directory(itempath, False, go_buttons_enabled, False, False)
					self.recursive = temp
				else:
					inputlist.append(item)
			for item in self.image_list:
				inputlist.append(item)
				if first_image_found and not second_image_found:
					second_image_found = True
					second_image = item
					second_image_came_from_dir = False
				if item == init_image:
					first_image_found = True
					first_image = item
					first_image_came_from_dir = False
					self.curr_img_in_list = len(inputlist)-1
		self.image_list = []
		for item in inputlist:
			if not self.closing_app:
				if os.path.isfile(item):
					if self.valid_image(item):
						if not second_image_found and first_image_found:
							second_image_found = True
							second_image = item
							second_image_came_from_dir = False
						if not first_image_found:
							first_image_found = True
							first_image = item
							first_image_came_from_dir = False
						self.image_list.append(item)
						if self.verbose:
							self.images_found += 1
							print _("Found: %(item)s [%(number)i]") % {'item': item, 'number': self.images_found}
				else:
					# If it's a directory that was explicitly selected or passed to
					# the program, get all the files in the dir.
					# Retrieve only images in the top directory specified by the user
					# unless explicitly told to recurse (via -R or in Settings>Preferences)
					folderlist.append(item)
					if not second_image_found:
						# See if we can find an image in this directory:
						self.stop_now = False
						self.expand_directory(item, True, go_buttons_enabled, False, False)
						itemnum = 0
						while itemnum < len(self.image_list) and not second_image_found:
							if os.path.isfile(self.image_list[itemnum]):
								if not second_image_found and first_image_found:
									second_image_found = True
									second_image_came_from_dir = True
									second_image = self.image_list[itemnum]
									self.set_go_navigation_sensitivities(True)
									go_buttons_enabled = True
									while gtk.events_pending():
										gtk.main_iteration(True)
								if not first_image_found:
									first_image_found = True
									first_image = self.image_list[itemnum]
									first_image_came_from_dir = True
							itemnum += 1
				# Load first image and display:
				if first_image_found and not first_image_loaded and self.curr_img_in_list <= len(self.image_list)-1:
					first_image_loaded = True
					if self.slideshow_mode:
						self.toggle_slideshow(None)
					if self.verbose and self.currimg.isloaded:
						print _("Loading: %s") % self.currimg.name
					self.load_new_image2(False, False, True, True)
					# Calling load_new_image2 will reset the following two vars
					# to 0, so ensure they are -1 again (no images preloaded)
					self.previmg.unload_pixbuf()
					self.nextimg.unload_pixbuf()
					self.previmg_width = self.currimg.width
					self.image_loaded = True
					first_image_loaded_successfully = True
					if not self.closing_app:
						while gtk.events_pending():
							gtk.main_iteration(True)
					if first_image_came_from_dir:
						self.image_list = []
				# Pre-load second image:
				if second_image_found and not second_image_preloaded and ((not second_image_came_from_dir and self.curr_img_in_list+1 <= len(self.image_list)-1) or second_image_came_from_dir):
					second_image_preloaded = True
					temp = self.image_list
					self.image_list = []
					while len(self.image_list) < self.curr_img_in_list+1:
						self.image_list.append(first_image)
					self.image_list.append(second_image)
					self.preload_next_image(False)
					self.image_list = temp
		if first_image_found:
			# Sort the filelist and folderlist alphabetically, and recurse into folderlist:
			if first_image_came_from_dir:
				self.add_folderlist_images(folderlist, go_buttons_enabled)
				self.do_image_list_stuff()
			else:
				self.do_image_list_stuff()
				self.add_folderlist_images(folderlist, go_buttons_enabled)

			prev_image = ''
			self.firstimgindex_subfolders_list = []
			for i, image in enumerate(self.image_list):
				if os.path.dirname(image) != os.path.dirname(prev_image):
					self.firstimgindex_subfolders_list.append(i)
				prev_image = image

			if not self.closing_app:
				while gtk.events_pending():
					gtk.main_iteration(True)
		if not first_image_loaded_successfully:
			self.image_load_failed(False, init_image)
		else:
			if self.verbose:
				print "name:" + self.currimg.name
			self.curr_img_in_list = self.image_list.index(self.currimg.name)
			self.update_title()
		self.searching_for_images = False
		self.update_statusbar()
		self.register_file_with_recent_docs(self.currimg.name)
		self.set_go_navigation_sensitivities(False)
		self.set_slideshow_sensitivities()
		self.thumbpane_update_images(True, self.curr_img_in_list)
		if not self.closing_app:
			self.change_cursor(None)
		self.recursive = False

	def sort_list_in_place(self, list):
		if self.no_sort:
			return

		#Sort based on a numerical aware sort or normal alphabetical sort
		if self.usettings['use_numacomp'] and HAVE_NUMACOMP:
			#Use case-sensitive sort?
			if self.usettings['case_numacomp']:
				list.sort(cmp=numacomp.numacomp)
			else:
				list.sort(cmp=numacomp.numacompi)
		else:
			list.sort(locale.strcoll)

	def remove_duplicates_from_list(self, list):
		found = set()
		newlist = []
		for item in list:
			if item not in found:
				newlist.append(item)
			found.add(item)
		return newlist

	def add_folderlist_images(self, folderlist, go_buttons_enabled):
		if len(folderlist) > 0:
			folderlist = self.remove_duplicates_from_list(folderlist)
			self.sort_list_in_place(folderlist)
			for item in folderlist:
				if not self.closing_app:
					if (not self.usettings['open_hidden_files'] and os.path.basename(item)[0] != '.') or self.usettings['open_hidden_files']:
						self.stop_now = False
						self.expand_directory(item, False, go_buttons_enabled, True, True)

	def do_image_list_stuff(self):
		if len(self.image_list) > 0:
			self.set_go_navigation_sensitivities(True)
			self.image_list = self.remove_duplicates_from_list(self.image_list)
			self.sort_list_in_place(self.image_list)

	def expand_directory(self, item, stop_when_second_image_found, go_buttons_enabled, update_window_title, print_found_msg):
		if not self.stop_now and not self.closing_app:
			folderlist = []
			filelist = []
			if not os.access(item, os.R_OK):
				return False
			item = item.decode('utf-8')
			for item2 in os.listdir(item):
				if not self.closing_app and not self.stop_now:
					while gtk.events_pending():
						gtk.main_iteration(True)
					item2 = item + os.sep + item2
					item_fullpath2 = os.path.abspath(item2)
					if (not self.usettings['open_hidden_files'] and os.path.basename(item_fullpath2)[0] != '.') or self.usettings['open_hidden_files']:
						if os.path.isfile(item_fullpath2) and self.valid_image(item_fullpath2):
							filelist.append(item2)
							if self.verbose and print_found_msg:
								self.images_found += 1
								print _("Found: %(fullpath)s [%(number)i]") % {'fullpath': item_fullpath2, 'number': self.images_found}
						elif os.path.isdir(item_fullpath2) and self.recursive:
							folderlist.append(item_fullpath2)
					elif self.verbose:
						print _("Skipping: %s") % item_fullpath2
			if len(self.image_list)>0 and update_window_title:
				self.update_title()
			# Sort the filelist and folderlist alphabetically:
			if len(filelist) > 0:
				self.sort_list_in_place(filelist)
				for item2 in filelist:
					if not item2 in self.image_list:
						self.image_list.append(item2)
						if stop_when_second_image_found and len(self.image_list)==2:
							return
						if not go_buttons_enabled and len(self.image_list) > 1:
							self.set_go_navigation_sensitivities(True)
							go_buttons_enabled = True
			# Recurse into the folderlist:
			if len(folderlist) > 0:
				self.sort_list_in_place(folderlist)
				for item2 in folderlist:
					if not self.stop_now:
						self.expand_directory(item2, stop_when_second_image_found, go_buttons_enabled, update_window_title, print_found_msg)

	def register_file_with_recent_docs(self, imgfile):
		self.recent_file_add_and_refresh(imgfile)
		if os.path.isfile(imgfile) and gtk.check_version(2, 10, 0) == None:
			try:
				gtk_recent_manager = gtk.recent_manager_get_default()
				uri = ''
				if imgfile[:7] != 'file://':
					uri = 'file://'
				uri = uri + urllib.pathname2url(os.path.abspath(imgfile.encode('utf-8')))
				gtk_recent_manager.add_item(uri)
			except:
				#Isnt currently functional on win32
				if sys.platform == "win32":
					pass
				else:
					raise

	def valid_image(self, file):
		test = gtk.gdk.pixbuf_get_file_info(file)
		if test == None:
			return False
		elif test[0]['name'] == "wbmp":
			# some regular files are thought to be wbmp for whatever reason,
			# so let's check further.. :(
			try:
				test2 = gtk.gdk.pixbuf_new_from_file(file)
				return True
			except:
				return False
		else:
			return True

	def toggle_slideshow(self, action):
		if len(self.image_list) > 1:
			if not self.slideshow_mode:
				if self.usettings['slideshow_in_fullscreen'] and not self.fullscreen_mode:
					self.enter_fullscreen(None)
				self.slideshow_mode = True
				self.update_title()
				self.set_slideshow_sensitivities()
				if not self.curr_slideshow_random:
					self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_next_image, "ss", True)
				else:
					self.reinitialize_randomlist()
					self.timer_delay = gobject.timeout_add(int(self.curr_slideshow_delay*1000), self.goto_random_image, "ss")
				self.ss_start.hide()
				self.ss_stop.show()
				timer_screensaver = gobject.timeout_add(1000, self.disable_screensaver_in_slideshow_mode)
			else:
				self.slideshow_mode = False
				gobject.source_remove(self.timer_delay)
				self.update_title()
				self.set_slideshow_sensitivities()
				self.set_zoom_sensitivities()
				self.ss_stop.hide()
				self.ss_start.show()

	def get_firstimgindex_curr_next_prev_subfolder(self, img_in_list):
		"""Returns a tuple (current [0], next [1], previous [-1]) firstimgindex"""
		if len(self.firstimgindex_subfolders_list) >= 2: #subfolders
			for i, firstimgindex in enumerate(self.firstimgindex_subfolders_list):
				if img_in_list < firstimgindex:
					return self.firstimgindex_subfolders_list[i-1], self.firstimgindex_subfolders_list[i], self.firstimgindex_subfolders_list[i-2]
			return self.firstimgindex_subfolders_list[-1], self.firstimgindex_subfolders_list[0], self.firstimgindex_subfolders_list[-2]
		else:
			return (-1,-1,-1)

	def get_numimg_subfolder(self, firstimgindex_subfolder):
		for i, index in enumerate(self.firstimgindex_subfolders_list):
			if index == firstimgindex_subfolder:
				if i < len(self.firstimgindex_subfolders_list)-1:
					return self.firstimgindex_subfolders_list[i+1] - firstimgindex_subfolder
				else:
					return len(self.image_list) - firstimgindex_subfolder
		return -1

	def update_title(self):
		if len(self.image_list) == 0:
			title = __appname__
		else:
			subfoldertitle = ''
			firstimgindex_curr_subfolder = self.get_firstimgindex_curr_next_prev_subfolder(self.curr_img_in_list)[0]
			if firstimgindex_curr_subfolder > -1:
				currimg_subfolder = self.curr_img_in_list - firstimgindex_curr_subfolder + 1
				numimg_curr_subfolder = self.get_numimg_subfolder(firstimgindex_curr_subfolder)
				subfoldertitle = _("%(current)i of %(total)i") % {'current': currimg_subfolder, 'total': numimg_curr_subfolder} + ' '
			title = __appname__ + " - " + subfoldertitle + _("[%(current)i of %(total)i]") % {'current': self.curr_img_in_list+1, 'total': len(self.image_list)} + ' ' + os.path.basename(self.currimg.name)

			if self.slideshow_mode:
				title = title + ' - ' + _('Slideshow Mode')
		self.window.set_title(title)

	def slideshow_controls_show(self):
		if not self.slideshow_controls_visible and not self.controls_moving:
			self.slideshow_controls_visible = True

			self.ss_delayspin.set_value(self.curr_slideshow_delay)
			self.ss_randomize.set_active(self.curr_slideshow_random)

			if self.slideshow_mode:
				self.ss_start.set_no_show_all(True)
				self.ss_stop.set_no_show_all(False)
			else:
				self.ss_start.set_no_show_all(False)
				self.ss_stop.set_no_show_all(True)

			(xpos, ypos) = self.window.get_position()
			screen = self.window.get_screen()
			self.slideshow_window.set_screen(screen)
			self.slideshow_window2.set_screen(screen)

			self.slideshow_window.show_all()
			self.slideshow_window2.show_all()
			if not self.closing_app:
				while gtk.events_pending():
					gtk.main_iteration()

			ss_winheight = self.slideshow_window.allocation.height
			ss_win2width = self.slideshow_window2.allocation.width
			winheight = self.window.allocation.height
			winwidth = self.window.allocation.width
			y = -3.0
			self.controls_moving = True
			while y < ss_winheight:
				self.slideshow_window.move(2+xpos, int(winheight-y-2)+ypos)
				self.slideshow_window2.move(winwidth-ss_win2width-2+xpos, int(winheight-y-2)+ypos)
				y += 0.05
				if not self.closing_app:
					while gtk.events_pending():
						gtk.main_iteration()
			self.controls_moving = False

	def slideshow_controls_hide(self):
		if self.slideshow_controls_visible and not self.controls_moving:
			self.slideshow_controls_visible = False

			(xpos, ypos) = self.window.get_position()

			ss_winheight = self.slideshow_window.allocation.height
			ss_win2width = self.slideshow_window2.allocation.width
			winheight = self.window.allocation.height
			winwidth = self.window.allocation.width
			y = float(self.slideshow_window.allocation.height*1.0)
			self.controls_moving = True
			while y > -3:
				self.slideshow_window.move(2+xpos, int(winheight-y-2)+ypos)
				self.slideshow_window2.move(winwidth-ss_win2width-2+xpos, int(winheight-y-2)+ypos)
				y -= 0.05
				if not self.closing_app:
					while gtk.events_pending():
						gtk.main_iteration()
			self.controls_moving = False

	def disable_screensaver_in_slideshow_mode(self):
		if self.slideshow_mode and self.usettings['disable_screensaver']:
			test = os.spawnlp(os.P_WAIT, "/usr/bin/xscreensaver-command", "xscreensaver-command", "-deactivate")
			if test <> 127:
				timer_screensaver = gobject.timeout_add(1000, self.disable_screensaver_in_slideshow_mode)

	def main(self):
		gtk.gdk.threads_enter()
		gtk.main()
		gtk.gdk.threads_leave()

class ImageData:
	
	# Define EXIF Orientation values
	ORIENT_NORMAL = 1
	ORIENT_LEFT   = 8
	ORIENT_MIRROR = 3
	ORIENT_RIGHT  = 6

	def __init__(self, index=-1, name="", width=0, heigth=0, pixbuf=None,
				pixbuf_original=None, pixbuf_rotated=None, zoomratio=1, animation=False):
		self.index = index
		self.name = name
		self.width_original = width
		self.height_original = heigth
		self.width = width
		self.height = heigth
		self.pixbuf = pixbuf
		self.pixbuf_original = pixbuf_original
		self.pixbuf_rotated = pixbuf_rotated
		self.zoomratio = zoomratio
		self.animation = animation
		self.isloaded = (name != "")
		self.fileinfo = None

	def load_pixbuf(self, name, index=-2):
		# Load the image in name into self.pixbuf_original
		animtest = gtk.gdk.PixbufAnimation(name)
		self.animation = not animtest.is_static_image()
		if self.animation:
			self.pixbuf_original = animtest
		else:
			self.pixbuf_original = animtest.get_static_image()
		self.name = name
		self.index = index
		self.pixbuf = self.pixbuf_original
		self.width = self.pixbuf.get_width()
		self.height = self.pixbuf.get_height()
		self.width_original = self.width
		self.height_original = self.height
		self.orientation = ImageData.ORIENT_NORMAL
		if HAS_EXIF :
			exifd = pyexiv2.ImageMetadata(self.name)
			exifd.read()
			if "Exif.Image.Orientation" in exifd.exif_keys :
				self.orientation = exifd["Exif.Image.Orientation"].value
				if self.orientation == ImageData.ORIENT_LEFT :
					self.rotate_pixbuf(90)
				elif self.orientation == ImageData.ORIENT_MIRROR : 
					self.rotate_pixbuf(180)
				elif self.orientation == ImageData.ORIENT_RIGHT :
					self.rotate_pixbuf(270)
		self.zoomratio = 1
		self.isloaded = True
		self.fileinfo = gtk.gdk.pixbuf_get_file_info(self.name)[0]

	def unload_pixbuf(self):
		self.index = -1
		self.width = 0
		self.height = 0
		self.width_original = 0
		self.height_original = 0
		self.name = ""
		self.zoomratio = 1
		self.animation = False
		self.pixbuf = None
		self.pixbuf_original = None
		self.orientation = None
		self.isloaded = False
		self.fileinfo = False
	
	def writable_format(self):
		if not self.isloaded:
			return False
		self.fileinfo['is_writable']
                return True

	def zoom_pixbuf(self, zoomratio, quality, colormap):
		# Always start with the original image to preserve quality!
		# Calculate image size:
		if self.animation:
			return
		final_width = int(self.pixbuf_original.get_width() * zoomratio)
		final_height = int(self.pixbuf_original.get_height() * zoomratio)
		# Scale image:
		if self.pixbuf_original.get_has_alpha():
			light_grey = colormap.alloc_color('#666666', True, True)
			dark_grey = colormap.alloc_color('#999999', True, True)
			self.pixbuf = self.pixbuf_original.composite_color_simple(final_width, final_height, quality, 255, 8, light_grey.pixel, dark_grey.pixel)
		else:
			self.pixbuf = self.pixbuf_original.scale_simple(final_width, final_height, quality)
		self.width, self.height = final_width, final_height
		self.zoomratio = zoomratio

	def transform_pixbuf(self, func) :
		def transform(old_pix, func) :
			width = old_pix.get_width()
			height = old_pix.get_height()
			d, w, h, rws = func(old_pix.get_pixels(), width, height, old_pix.get_rowstride(), old_pix.get_n_channels())
			if d:
				return gtk.gdk.pixbuf_new_from_data(d, old_pix.get_colorspace(), old_pix.get_has_alpha(), old_pix.get_bits_per_sample(), w, h, rws), w, h
			return old_pix, width, height
		self.pixbuf_original, self.width_original, self.height_original = transform(self.pixbuf_original, func)
		self.pixbuf         , self.width         ,  self.height         = transform(self.pixbuf         , func)

	def flip_pixbuf(self, vertical):
		self.transform_pixbuf(imgfuncs.vert if vertical else imgfuncs.horiz)

	def rotate_pixbuf(self, full_angle):
		angle = full_angle - (int(full_angle) / 360) * 360
		if angle:
			d = None
			if angle % 270 == 0:
				self.transform_pixbuf(imgfuncs.right)
			elif angle % 180 == 0:
				self.transform_pixbuf(imgfuncs.mirror)
			elif angle % 90 == 0:
				self.transform_pixbuf(imgfuncs.left)

	def resize(self, w, h, quality):
		self.pixbuf_original = self.pixbuf_original.scale_simple(w, h, quality)
		self.reset_wh()

	def saturation(self, satval):
		self.pixbuf_original.saturate_and_pixelate(self.pixbuf_original, satval, False)
		self.pixbuf.saturate_and_pixelate(self.pixbuf, satval, False)

	def crop(self, coords):
		temp_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, self.pixbuf_original.get_has_alpha(), 8, coords[2], coords[3])
		self.pixbuf_original.copy_area(coords[0], coords[1], coords[2], coords[3], temp_pixbuf, 0, 0)
		self.pixbuf_original = temp_pixbuf
		self.reset_wh()

	def reset_wh(self):
		self.width_original = self.pixbuf_original.get_width()
		self.height_original = self.pixbuf_original.get_height()

if __name__ == "__main__":
	base = Base()
	base.main()
