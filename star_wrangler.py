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

from star_common import srun, json_loader, tab_printer, plural, search_list
from star_common import error, mkdir, samepath, indenter, rfs
from star_common import auto_columns as auto_cols

# Loaded module members
MYMOD = star_namer.load_mod(sys.argv[1])
MM = dict(inspect.getmembers(MYMOD))
MYIMPORTS = odict()         # Required modules to be imported
FUNC_UNDEF = dict()         # Dict of functions to undefined words
MODIMPORTS = dict()         # Dict of module : import lines in module
SRC = dict()                # Dict of modules to source code lines
ONEFILE = False             # Output as single file or with an additional function file
MAX_LEVEL = 9               # Max amount of recursion to allow, 0 = unlimited


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

	def visit_Name(self, node):
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


def get_words(code):
	"Read block of code and get unique functions"
	parse = ast.parse(code)
	return {node.id for node in ast.walk(parse) if isinstance(node, ast.Name)}


def load_imports(module):
	"Given a module, get it's import lines"
	if module in MODIMPORTS:
		return MODIMPORTS[module]
	out = []
	for line in getsource(module):
		if re.match('[^\\W]*', line):
			words = line.split()
			if 'import' in words:
				out.append(line)
		if line.startswith('def'):
			break
	MODIMPORTS[module] = out
	return out


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
	data = srun(PYLINT, '--from-stdin stdin --output-format=json --disable=W0312', input=code, hidewarning=True)
	for item in json_loader('\n'.join(data)):
		idc = item['message-id']
		msg = item['message']
		# print(msg)
		if idc == 'E0602':          # undefined variable:
			yield re.sub('Undefined variable ', '', msg).strip("'")


def process(func, functions, caller=None, level=0):
	print = partial(tab_printer, level=level)

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
		if parent not in functions:
			print("Processing method", func, "of", parent)
			print(func.__name__, '=', func)

			if hasattr(func, '__self__'):
				print("Detected", func.__name__, "is bound method")
				for line in getsource(mod):
					if line.startswith(func.__name__):
						print(line)
						functions[func] = [line]
			func = parent
		else:
			print("Already processed:", parent)
			return

	# Get code
	if func not in functions:
		code = getsource(func)
		functions[func] = code
		print("Loaded:", plural(len(code), 'line'), 'of code')
	else:
		code = functions[func]

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
			if subfunc != func:
				if MAX_LEVEL and level + 1 < MAX_LEVEL:
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

################################################################################
# Main


def get_code_words(filename):
	functions = odict()     # Functions and code found in MYMOD

	with open(filename) as f:
		source = f.read()

	# Scrape imports from source:
	source_imports = set()
	mod_name = os.path.basename(MYMOD.__file__).rstrip('.py')
	import_expr = 'from ' + mod_name + ' import'
	common_imports = []
	out = []
	deleted_lines = 0
	source = source.splitlines()
	for num, line in enumerate(source):
		if line.startswith('import ') or (line.startswith('from') and ' import ' in line):
			if line.startswith(import_expr):
				common_imports += re.sub('.*import ', '', line).split()
				deleted_lines += 1
				continue
			start = line.split().index('import')
			for i in line.split()[start + 1:]:
				if i != '*':
					source_imports.add(i)
		if line.startswith('def'):
			_func_start = num - deleted_lines
			break
		out.append(line)
	source = out + source[num:]


	if not common_imports:
		error("Could not find any common imports in", filename, "for module name:", mod_name)

	# Read through every line in the source code file, branching into the imports for more functions
	if '*' in common_imports:
		# gen = iter([node.id for node in ast.walk(ast.parse('\n'.join(source))) if isinstance(node, ast.Name)])
		gen = iter(star_namer.scrape_wildcard(filename, MM).keys())
	else:
		gen = iter(common_imports)

	for word in gen:
		word = word.strip(',')
		if word in MM.keys():
			func = MM[word]

			# For non functions, do an import
			if not callable(func):
				if isinstance(func, types.ModuleType):
					print("Skipping root module:", func.__name__)
				elif word in MM.keys() and not word.startswith('__'):
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


def main():

	print('Mod Functions:')
	auto_cols([(key, str(val).replace('\n', ' ')) for key, val in sorted(MM.items())], crop=[0, 200])
	print("\n")

	filenames = sys.argv[2:]
	if not filenames:
		error("You must specify at least one filename")

	if ONEFILE:
		filename = filenames[0]
		output_name = os.path.join('/tmp/publish', os.path.basename(filename))
	else:
		output_name = os.path.join('/tmp/publish', shared.OUTPUT_NAME)
	mkdir('/tmp/publish')

	functions = odict()         # Dict of function names to code
	file_functions = dict()     # Dict filenames to function dicts
	for filename in filenames:
		dirname = os.path.dirname(filename)
		if samepath(filename, dirname, output_name):
			error("Cannot overwrite self!")
		sub = get_code_words(filename)

		file_functions[filename] = sub
		for func in sub:
			if func not in functions:
				functions[func] = sub[func]

	print('\n' * 5)
	print("Done. Outputting to file:", output_name)
	print('#' * 80, '\n')

	# Write code to output
	output = []

	def owl(*args):
		"Output write lines"
		output.append(' '.join(args))

	# Header
	if not ONEFILE:
		owl("#!/usr/bin/python3")
		owl(shared.HEADER.strip())
	if ONEFILE:
		owl(shared.HEADER.replace('file', 'section').strip())

	# Write import lines to top of the file
	print("Imports:", *MYIMPORTS.items(), sep='\n')
	owl('')
	func_names = [get_func_name(func) for func in functions]
	for line in sorted(MYIMPORTS.values(), key=len):
		words = re.sub('.* import ', '', line).split()
		if not any([word in func_names for word in words]):
			owl(line)
		else:
			print("Skipping locally ref import line:", line)
	if MYIMPORTS:
		owl("\n")

	# Functions
	for func, code in reversed(functions.items()):
		owl('\n'.join(code))
		owl('\n')

	# Put it all together and output
	'''
	if len(output) <= 2:
		output = source
	else:
		# output = source[:func_start] + ['#'*80] + output + ['#'*80,'',''] + source[func_start:]
	'''
	output.append("\n'''\n" + shared.FOOTER.strip())
	output.append(time.strftime('%Y-%m-%d', time.localtime()))
	output.append("'''")

	with open(output_name, 'w') as out:
		for line in output:
			out.write(line + '\n')

	# List imports for each file for copy paste
	# https://www.python.org/dev/peps/pep-0008/#imports
	print('\n')
	for filename, sub in file_functions.items():
		if len(filenames) > 1:
			print(filename, "functions to be imported:")
		print("\nimport", shared.OUTPUT_NAME.rstrip('.py'), "as common")
		words = [get_func_name(func) for func in reversed(sub.keys())]
		for line in indenter(', '.join(words), header='from common import ', wrap=80):
			print(line.rstrip(','))
		print('\n')

	# Finished
	print(rfs(os.path.getsize(output_name)), 'of code saved to', output_name)
	srun("chmod +x " + output_name)
	print("Copy to script directory with:")
	print('cp', output_name, os.path.join(os.path.dirname(os.path.realpath(filename)), shared.OUTPUT_NAME))


if __name__ == "__main__":
	PYLINT = star_namer.check_pylint()
	main()
