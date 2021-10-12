#!/usr/bin/python3
# The universe contains all the functions used by the stars

import os
import re
import sys
import ast
import types
import inspect
import importlib
from functools import partial

import shared
from sd.common import search_list, warn, json_loader, error, DotDict, quickrun as qrun

CACHED = DotDict()			#Function static variables containing a cache of results

def get_pylint():
	"Check pylint version and return file path"

	if CACHED.pylint:
		return CACHED.pylint

	pylint = shared.PYLINT
	if not os.path.exists(pylint):
		warn("Pylint path does not exist:", pylint)
		print("Please install: https://www.pylint.org/#install")
		print("and then set the correct path in shared.py")
		sys.exit(1)

	version = qrun(pylint, '--version')
	version = search_list('pylint', version, getfirst=True).split()[-1].split('.')[:2]
	if list(map(int, version)) < [2, 4]:
		error("Pylint must be at least version 2.4")

	CACHED.pylint = pylint
	return pylint


def load_imports(module):
	"Given a module, get it's import lines"
	cache = CACHED.load_imports				# Dict of module : import lines in module

	if module in cache:
		return cache[module]
	cache[module] = [line for _num, line in scrape_imports('\n'.join(getsource(module)))]
	return cache[module]


def getsource(item):
	"Retrieve the source of module or function"
	cache = CACHED.getsource				# Dict of functions to source code lines
	if not any([inspect.isclass(item), inspect.ismodule(item), inspect.ismethod(item), inspect.isfunction(item)]):
		print("Confused by item:", item)
		print("Trying one level up:", type(item))
		item = type(item)

	if item not in cache:
		code = inspect.getsource(item)
		cache[item] = code.splitlines()
	return cache[item]


def undefined(func):
	"Run code through pylint and get all undefined variables"
	cache = CACHED.undefined			# Dict of functions to undefined words

	if func in cache:
		return cache[func]

	code = '\n'.join(getsource(func))
	data = qrun(get_pylint(), '--from-stdin stdin --output-format=json --disable=W0312'.split(),
				stdin=code, hidewarning=True)

	words = set()
	for item in json_loader('\n'.join(data)):
		idc = item['message-id']
		msg = item['message']
		# print(msg)
		if idc == 'E0602':          # undefined variable:
			word = re.sub('Undefined variable ', '', msg).strip("'")
			words.add(word)
	return words


def get_undefined(source):
	"Run souce code through pylint and get each undefined variable"
	data = qrun(get_pylint(), '--from-stdin stdin --output-format=json --disable=W0312'.split(),
				stdin=source, hidewarning=True)
	for item in json_loader('\n'.join(data)):
		idc = item['message-id']
		if idc == 'E0602':          # undefined variable:
			yield item


def scrape_imports(source):
	"Given source code, scrape it's import lines"
	tree = ast.parse(source)
	for node in ast.iter_child_nodes(tree):
		if isinstance(node, (ast.Import, ast.ImportFrom)):
			for var in node.names:
				out = [var.name]
				if var.asname:
					out += ['as', var.asname]
				if isinstance(node, ast.ImportFrom):
					out = ['from', node.module, 'import'] + out
				else:
					out = ['import'] + out
				yield node.lineno - 1, ' '.join(out)


def iter_nodes(code):
	"Return id names for every node in the code"
	for node in ast.walk(ast.parse(code)):
		if isinstance(node, ast.Name):
			yield node.id


class GetVars(ast.NodeVisitor):
	"Usage: GetVars().search(ast.parse(code), 'eprint')"
	def __init__(self):
		self.lineno = []
		self.expr = ''

	def visit_Name(self, node):         # pylint: disable=C0103
		if isinstance(node.ctx, ast.Store):
			if node.id == self.expr:
				self.lineno.append(node.lineno)

	def search(self, node, expr):
		self.expr = expr
		self.visit(node)
		return self.lineno


def get_line(module, expr):
	"Search module for global variable definition line"
	print("\nSearching for:", expr, 'in', module)
	code = '\n'.join(getsource(module))
	numbers = GetVars().search(ast.parse(code), expr)
	code = code.splitlines()
	for num in numbers:
		line = code[num - 1]
		if line and not line.startswith((' ', '\t')):
			# print(repr(line))
			return line
	return None


def get_class_that_defined_method(meth):
	"Credit to Yoel: https://stackoverflow.com/a/25959545/11343425"
	if isinstance(meth, partial):
		return get_class_that_defined_method(meth.func)
	if inspect.ismethod(meth) or \
		(inspect.isbuiltin(meth) and
		 getattr(meth, '__self__', None) is not None and
		 getattr(meth.__self__, '__class__', None)):
		for cls in inspect.getmro(meth.__self__.__class__):
			if meth.__name__ in cls.__dict__:
				return cls
		meth = getattr(meth, '__func__', meth)  # fallback to __qualname__ parsing
	if inspect.isfunction(meth):
		cls = getattr(inspect.getmodule(meth),
					  meth.__qualname__.split('.<locals>', 1)[0].rsplit('.', 1)[0], None)
		if isinstance(cls, type):
			return cls
	return getattr(meth, '__objclass__', None)  # handle special descriptor objects


def get_modname(mod):
	"Get module name"
	cache = CACHED.get_modname			# Dict of functions to undefined words

	# print("get_modname:", mod)
	if mod not in cache:
		if hasattr(mod, '__file__'):
			name = ''.join(os.path.basename(mod.__file__).split('.py')[:-1])
		else:
			name = mod.__name__
		cache[mod] = name
	return cache[mod]


def get_func_name(func):
	"Return the name for a function in functions"
	if type(func) == str:
		name = func
	else:
		try:
			name = func.__name__
		except AttributeError:
			# hasattr fails here:
			# https://docs.python.org/3/reference/expressions.html#atom-identifiers
			name = str(func)
	return name


def scrape_wildcard(filename, modvars):
	"Get variables imported from module in wild * import"
	unused = []
	cmd = [get_pylint(), filename] + '--output-format=json --disable=W0312'.split()
	for item in json_loader('\n'.join(qrun(cmd, hidewarning=True))):
		if item['message-id'] == 'W0614':
			line = item['message']
			line = re.sub('^Unused import ', '', line)
			line = re.sub(' from wildcard import$', '', line)
			unused.append(line)

	if not unused:
		warn("Pylint did not detect any unused imports for", filename, '\n'*2,
			 "Make sure there is a:", '\n',
			 "from __modulename__ import *", '\n',
			 "line in the file", delay=0)
		return {}

	out = dict()
	for name in set(modvars) - set(unused):
		if not name.startswith('__'):
			func = modvars[name]
			if not isinstance(func, types.ModuleType):
				out[name] = modvars[name]
	return out


def load_mod(filename):
	"Load a module given a filename"
	backup = sys.path.copy()
	sys.path.insert(0, os.path.dirname(filename))
	name = os.path.basename(filename)
	name = os.path.splitext(name)[0]
	print("Loading", name, 'from', sys.path[0])
	mod = importlib.import_module(name)
	sys.path = backup
	return mod

'''
def load_mod(filename):
	# Fails with a class: https://stackoverflow.com/q/67663614/11343425
	name = os.path.basename(filename)
	name = os.path.splitext(name)[0]
	spec = importlib.util.spec_from_file_location("mymod", filename)
	mymod = importlib.util.module_from_spec(spec)
	if execute:
		os.chdir('/data/code/A')			#todo fix
		spec.loader.exec_module(mymod)
		os.chdir('/mnt/3/data/scripts/master')
	return mymod
'''

'''
def load_mod(filename):
	# Fails in non-interactive mode???
	name = os.path.basename(filename)
	name = os.path.splitext(name)[0]
	cur = os.getcwd()
	target = os.path.dirname(filename)
	if target:
		os.chdir(target)
	print(name, os.getcwd())
	mod = importlib.import_module(name)
	os.chdir(cur)
	return mod
'''


def get_members(filename):
	"Get functions in module"
	mod = load_mod(filename)
	return dict(inspect.getmembers(mod, inspect.isfunction))
