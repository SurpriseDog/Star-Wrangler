#!/usr/bin/python3
# Take a script and replace all local imports with actual code from the module
# Usage ./star_wrangler.py <module file> <script 1> <script 2> ...
# Requires pylint: https://www.pylint.org/#install

import os
import re
import ast
import sys
import time
import types
import inspect
from functools import partial
from collections import OrderedDict as odict

import shared
import star_namer

from star_common import json_loader, tab_printer, plural, error, mkdir
from star_common import samepath, indenter, rfs, auto_columns as auto_cols
from star_common import warn, easy_parse, quickrun as qrun

MYIMPORTS = odict()         # Required modules to be imported
FUNC_UNDEF = dict()         # Dict of functions to undefined words
MODIMPORTS = dict()         # Dict of module : import lines in module
SRC = dict()                # Dict of modules to source code lines


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


def load_imports(module):
	"Given a module, get it's import lines"
	if module in MODIMPORTS:
		return MODIMPORTS[module]
	MODIMPORTS[module] = [line for _num, line in scrape_imports('\n'.join(getsource(module)))]
	return MODIMPORTS[module]


def getsource(item):
	"Retrieve the source of module or function"
	if not any([inspect.isclass(item), inspect.ismodule(item), inspect.ismethod(item), inspect.isfunction(item)]):
		print("Confused by item:", item)
		print("Trying one level up:", type(item))
		item = type(item)

	if item not in SRC:
		code = inspect.getsource(item)
		SRC[item] = code.splitlines()
	return SRC[item]


class GetVars(ast.NodeVisitor):
	"Usage: GetVars().search(ast.parse(code), 'eprint')"

	def __init__(self):
		self.lineno = []
		self.expr = ''

	def visit_Name(self, node):			#pylint: disable=C0103
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


def get_words(code):
	"Read block of code and get unique functions"
	parse = ast.parse(code)
	return {node.id for node in ast.walk(parse) if isinstance(node, ast.Name)}



def get_class_that_defined_method(meth):
	"Credit to Yoel: https://stackoverflow.com/a/25959545/11343425"
	if isinstance(meth, partial):
		return get_class_that_defined_method(meth.func)
	if inspect.ismethod(meth) or \
	(inspect.isbuiltin(meth) and \
	getattr(meth, '__self__', None) is not None and \
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


def undefined(code):
	"Run code through pylint and get all undefined variables"
	# print('code=', code)
	data = qrun(PYLINT, '--from-stdin stdin --output-format=json --disable=W0312'.split(),
		        input=code, hidewarning=True)
	for item in json_loader('\n'.join(data)):
		idc = item['message-id']
		msg = item['message']
		# print(msg)
		if idc == 'E0602':          # undefined variable:
			yield re.sub('Undefined variable ', '', msg).strip("'")





def process(func, functions, caller=None, level=0, max_level=9):
	'''
	Process a function
	level = current recurrsion level
	max_level = Max amount of recursion to allow, 0 = unlimited
	'''

	print = partial(tab_printer, level=level)		#pylint: disable=W0622

	def alias_finder(name, module):
		'''Find a line of code that is the aliases a function,
		Ex: auto_cols = autocolumns
		Global declarations only!
		'''
		print("searching for:", name, 'in', module)
		for line in getsource(module):
			if line.startswith(name):
				print('alias found:', line)
				functions[name] = [line]
				functions.move_to_end(name, last=False)

	if level:
		print('\n\n')

	mod = inspect.getmodule(func)

	# If reached a default mod, return
	if mod.__name__ in sys.builtin_module_names or mod.__file__.startswith('/usr/lib'):
		print("Looking for func:", func.__name__, "in caller", caller)
		# search_imports(func.__name__, caller)
		return

	if func == mod:
		print("Looking for mod", func.__name__, "in caller", caller.__name__)
		# search_imports(func.__name__, caller)
		return
	else:
		print(func, type(func), 'from module', mod)

	# If it's a method of a class, get the whole class
	if inspect.ismethod(func):
		parent = get_class_that_defined_method(func)
		if get_func_name(parent) not in functions:
			print("Processing method", func, "of", parent)
			print(func.__name__, '=', func)

			if hasattr(func, '__self__'):
				print("Detected", func.__name__, "is bound method")
				alias_finder(func.__name__, mod)
			func = parent
		else:
			print("Already processed:", parent)
			return

	# Get code
	name = get_func_name(func)
	if name not in functions:
		code = getsource(func)
		functions[name] = code
		print("Loaded:", plural(len(code), 'line'), 'of code')
	else:
		code = functions[name]

	# Get words from within function
	if func in FUNC_UNDEF:
		words = FUNC_UNDEF[func]
	else:
		words = list(undefined('\n'.join(code)))
		FUNC_UNDEF[func] = words
	print('Function:', func, 'words = ', words)

	# Process child functions
	mod_vars = vars(mod)
	for word in words:
		if word in mod_vars.keys():
			subfunc = mod_vars[word]
			if word != subfunc.__name__:
				alias_finder(word, inspect.getmodule(subfunc))
			if subfunc != func:
				if max_level and level + 1 > max_level:
					continue
				process(subfunc, functions, caller=mod, level=level + 1)

	# Look for words imported by module
	for word in words:
		for line in load_imports(mod):
			if word in line.split():
				print('code:', repr(line))
				MYIMPORTS[word] = line
				break


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


def get_code_words(filename, members, common_imports):
	print("\n\nProcessing:", filename)
	functions = odict()     # Functions and code found in mymod



	# Read through every line in the source code file, branching into the imports for more functions
	if '*' in common_imports:
		gen = iter(star_namer.scrape_wildcard(filename, members).keys())
	else:
		gen = iter(common_imports)

	for word in gen:
		word = word.strip(',')
		if word in members.keys():
			func = members[word]

			# For non functions, do an import
			if not callable(func):
				if isinstance(func, types.ModuleType):
					print("Skipping root module:", func.__name__)
				elif word in members.keys() and not word.startswith('__'):
					print("Found root Variable:", word)
					if not hasattr(func, '__dict__'):
						code = func
						if type(func) == str:
							code = repr(func)
						else:
							code = func
						functions[word] = [word + ' = ' + code]
						continue
					else:
						functions[word] = [get_line(inspect.getmodule(func), word), ]

			if func not in functions:
				print('\n')
				process(func, functions, level=0)
	return functions

################################################################################
# Main


def main():
	args = [\
		["output", "output_name", str, shared.OUTPUT_NAME],
		"Output file name",
		["onefile", "", bool],
		"Combine script and functions in one file",
		]
	positionals = [\
		["mymod"],
		"Module name to copy function from",
		["scripts", '', list],
		"Python scripts to scan through",
		]

	args = easy_parse(args, positionals)
	mymod = star_namer.load_mod(args.mymod)
	mod_name = os.path.basename(mymod.__file__).rstrip('.py')
	members = dict(inspect.getmembers(mymod))
	onefile = args.onefile
	output_name = args.output_name.rstrip('.py')
	filenames = args.scripts

	if not filenames:
		error("You must specify at least one filename")
	for name in filenames:
		if not os.path.exists(name):
			error(name, "does not exist")

	if onefile:
		if len(filenames) != 1:
			error("--onefile mode can only be used with a single file")
		filename = filenames[0]
		output_filename = os.path.join('/tmp/Star_Wrangler', os.path.basename(filename))
	else:
		output_filename = os.path.join('/tmp/Star_Wrangler', output_name+'.py')
	mkdir('/tmp/Star_Wrangler')

	print('Mod Functions:')
	auto_cols([(key, str(val).replace('\n', ' ')) for key, val in sorted(members.items())], crop=[0, 200])
	print("\n")

	#Generate dict of required functions and their code
	functions = odict()         # Dict of function names to code
	file_functions = dict()     # Dict filenames to function dicts
	file_imports = dict()			# Dict of filenames to import lists
	for filename in filenames:
		dirname = os.path.dirname(filename)
		if samepath(filename, dirname, output_filename):
			error("Cannot overwrite self!")

		#source, common_imports, func_start = scrape_imports(filename, output_name, mymod)
		line_nums = set()
		imports = []
		with open(filename) as f:
			source = f.read()
			for num, line in scrape_imports(source):
				if mod_name in line:
					line_nums.add(num)
					imports.append(re.sub('.*import ', '', line))
		if not imports:
			warn("Could not find any common imports in", filename, "for module name:", mod_name)
		else:
			file_imports[filename] = imports
			sub = get_code_words(filename, members, [re.sub(' as .*$', '', word) for word in imports])
			file_functions[filename] = sub
			for func in sub:
				if func not in functions:
					functions[func] = sub[func]


	# Write code to output
	print('\n' * 5)
	print("Done. Outputting to file:", output_filename)
	print('#' * 80, '\n')
	output = []


	def owl(*args):
		"Output write lines"
		output.append(' '.join(args))


	# Header
	if not onefile:
		owl("#!/usr/bin/python3")
		owl(shared.HEADER.strip())
	if onefile:
		owl(shared.HEADER.replace('file', 'section').strip())


	# Write import lines to top of the file
	# print("Imports:", *MYIMPORTS.items(), sep='\n')
	owl('')
	#func_names = [get_func_name(func) for func in functions]
	func_names = functions.keys()
	for line in sorted(MYIMPORTS.values(), key=len):
		words = re.sub('.* import ', '', line).split()
		if not any([word in func_names for word in words]):
			owl(line)
		else:
			print("Skipping locally referenced import line:", line)
	if MYIMPORTS:
		owl("\n")


	# Functions
	for func, code in reversed(functions.items()):
		owl('\n'.join(code))
		owl('\n')


	# Put it all together and output
	if onefile:
		ie = max(line_nums)
		source = source.splitlines()
		for num in line_nums:
			source.pop(num)
		output = source[:ie] + ['#'*80] + output + ['#'*80, '', ''] + source[ie:]
	output.append("\n'''\n" + shared.FOOTER.strip())
	output.append(time.strftime('%Y-%m-%d', time.localtime()))
	output.append("'''")
	with open(output_filename, 'w') as out:
		for line in output:
			out.write(line + '\n')


	# List imports for each file for copy paste
	# https://www.python.org/dev/peps/pep-0008/#imports
	print('\n')
	for filename, words in file_imports.items():
		print(filename, "functions to be imported:", '\n')
		for line in indenter(', '.join(words), header='from ' + output_name + ' import ', wrap=80):
			print(line.rstrip(','))
		print('\n')


	# Finished
	print(rfs(os.path.getsize(output_filename)), 'of code saved to', output_filename)
	qrun('chmod', '+x', output_filename)
	print("Copy to script directory with:")
	print('cp', output_filename,
		  os.path.join(os.path.dirname(os.path.realpath(filename)), os.path.basename(output_filename)))


if __name__ == "__main__":
	PYLINT = star_namer.check_pylint()
	main()
