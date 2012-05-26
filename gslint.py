import gscommon as gs, margo
import sublime, sublime_plugin
import threading, Queue, time

DOMAIN = 'GsLint'

class FileRef(object):
	def __init__(self, view):
		self.view = view
		self.src = ''
		self.tm = 0.0
		self.state = 0
		self.reports = {}

class Report(object):
	def __init__(self, row, col, msg):
		self.row = row
		self.col = col
		self.msg = msg

class GsLintThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		self.daemon = True
		self.sem = threading.Semaphore()
		self.s = set()
		self.q = Queue.Queue()

	def putq(self, fn):
		with self.sem:
			if fn in self.s:
				return False
			self.s.add(fn)
			self.q.put(fn)
			return True

	def popq(self):
		fn = self.q.get()
		with self.sem:
			self.s.discard(fn)
		return fn

	def run(self):
		while True:
			fn = self.popq()
			fr = ref(fn, False)
			if fr:
				reports = {}
				resp, _ = margo.lint(fn, fr.src)
				for r in resp:
					row = r.get('row', 0)
					col = r.get('col', 0)
					msg = r.get('msg', '')
					if row >= 0 and msg:
						reports[row] = Report(row, col, msg)

				fr = ref(fn, False)
				if fr:
					with sem:
						fr.state = 1
						fr.reports = reports
						file_refs[fn] = fr

def highlight(fr):
	sel = fr.view.sel()[0].begin()
	row, _ = fr.view.rowcol(sel)

	if fr.state == 1:
		fr.state = 0
		cleanup(fr.view)

		regions = []
		flags = sublime.HIDDEN
		for r in fr.reports.values():
			line = fr.view.line(fr.view.text_point(r.row, 0))
			if r.col > 0:
				flags = sublime.DRAW_EMPTY_AS_OVERWRITE

			pos = line.begin() + r.col
			if pos >= line.end():
				pos = line.end()

			regions.append(sublime.Region(pos, pos))

		if regions:
			fr.view.add_regions(DOMAIN, regions, 'comment', 'dot', flags)
		else:
			fr.view.erase_regions(DOMAIN)

	msg = ''
	reps = fr.reports.copy()
	l = len(reps)
	if l > 0:
		msg = '%s (%d)' % (DOMAIN, l)
		r = reps.get(row)
		if r and r.msg:
			msg = '%s: %s' % (msg, r.msg)

	if fr.state != 0:
		msg = u'\u231B %s' % msg

	fr.view.set_status(DOMAIN, msg)

def cleanup(view):
	view.set_status(DOMAIN, '')
	view.erase_regions(DOMAIN)

def watch():
	global file_refs
	global th

	view = gs.active_valid_go_view()

	if gs.setting('gslint_enabled') is not True:
		if view:
			with sem:
				for fn in file_refs:
					fr = file_refs[fn]
					cleanup(fr.view)
				file_refs = {}
		sublime.set_timeout(watch, 2000)
		return

	if view and not view.is_loading():
		fn = view.file_name()
		fr = ref(fn)
		with sem:
			if fr:
				# always use the active view (e.g in split-panes)
				fr.view = view
				highlight(fr)
			else:
				fr = FileRef(view)

			file_refs[fn] = fr
			if fr.state == 0:
				src = view.substr(sublime.Region(0, view.size()))
				if src != fr.src:
					fr.src = src
					fr.tm = time.time()

				if fr.tm > 0.0:
					timeout = int(gs.setting('gslint_timeout', 500))
					delta = int((time.time() - fr.tm) * 1000.0)
					if delta >= timeout:
						fr.tm = 0.0
						fr.state = -1
						if not th:
							th = GsLintThread()
							th.start()
						th.putq(fn)

	sublime.set_timeout(watch, 500)

def ref(fn, validate=True):
	with sem:
		if validate:
			for fn, fr in file_refs.items():
				if not fr.view.window() or fn != fr.view.file_name():
					del file_refs[fn]
		return file_refs.get(fn)

def delref(fn):
	with sem:
		if fn in file_refs:
			del file_refs[fn]
try:
	init_once
except:
	init_once = True

	th = None
	sem = threading.Semaphore()
	file_refs = {}

	watch()
