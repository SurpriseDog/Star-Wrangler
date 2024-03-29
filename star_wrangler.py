#!/usr/bin/python3
# Take a script and replace all local imports with actual code from the module
# Usage ./star_wrangler.py <module file> <script 1> <script 2> ...
# Requires pylint: https://www.pylint.org/#install

import os
import re
import sys
import time
import shutil
import inspect
from collections import OrderedDict as odict

import shared
import universe

from sd.easy_args import easy_parse
from sd.columns import indenter, tab_printer, auto_cols
from sd.common import samepath, mkdir, error, rfs, plural, warn, quickrun as qrun

#Build: wrangler star_wrangler.py star_namer.py universe.py --dir . --name star_common	# nocommit
def get_args():
	"Get user arguments"

	opts = [
		["name", "output_name", str, shared.OUTPUT_NAME],
		"Output file name. Type: 'same' to copy.",
		["directory", "output_dir", str, '/tmp/Star_Wrangler'],
		"Output directory (must be different that source)",
		["onefile", "", bool],
		"Combine script and functions in one file",
		['max', 'max_level', int, 9],
		"Maxmimum recursion level when searching for function references",
		['nofollow', '', bool],
		"Don't follow imports to new modules instead of scraping import lines",
		['modnames', '', list],
		"Instead of searching for import lines with the module name, supply your own list",
		['ignore', '', list],
		"Ignore modules with the following names...",
		['functions', '', list],
		"Instead of a python file, why not just tell me which functions you would like?",
	]
	positionals = [
		["mymod"],
		"Module name to copy function from",
		["scripts", 'filenames', list],
		"Python scripts to scan through",
	]

	# Load the args:
	args = easy_parse(opts, positionals, usage='<module file> <script 1> <script 2> ...')

	# Error checking:
	if not args.filenames:
		error("You must specify at least two filenames")
	for name in args.filenames:
		if not os.path.exists(name):
			error(name, "does not exist")
	if args.onefile:
		if len(args.filenames) != 1:
			error("--onefile mode can only be used with a single file")

	# Convert ignored files to modnames (if applicable)
	for index, name in enumerate(args.ignore):
		if os.path.exists(name):
			new = ''.join(os.path.basename(name).split('.py')[:-1])
			args.ignore[index] = new
			print("Extracted", new, 'from', name)
	return args


class Processor():
	"Process a filename for undefined words found in mymod"
	term_width = shutil.get_terminal_size()[0] - 1

	def __init__(self, mymod, follow=True, ignore=None, max_level=9):
		self.imports = odict()         	 # Required modules to be imported
		self.words = dict()				 # Dict of words to functions
		self.functions = odict()	     # Functions to code found in self.mymod
		self.aliases = odict()			 # One line global definitions
		self.mymod = mymod				 # Module to look for code inside
		self.loaded = dict()			 # How many lines of code are loaded from each module
		self.ignore = ignore if ignore else []

		self.max_level = max_level		 # Max recursion level
		self.follow	= follow		     # Follow imports to new modules instead of scraping import lines


	def process(self, name, mod=None, level=0):
		'''Process a function'''
		#Change to process word instead of func to handle direct get_words

		def iprint(*args, **kargs):
			tab_printer(*args, level=level, header='', **kargs)


		def alias_finder(name, mod):
			'''Find a line of code that is the aliases a function: eprint = Eprinter()
			Ex: auto_cols = autocolumns
			Global declarations only!
			'''
			iprint("alias_finder searching for:", name, 'in', mod)
			for line in universe.getsource(mod):
				if line.startswith(name):
					iprint('alias found:', line)
					self.aliases[name] = line
					self.words[name] = line
					for word in universe.iter_nodes(line):
						if word != name:
							self.process(word, mod=mod, level=level+1)


		def search_imports(word, amod=None):
			"Search import lines for word"
			if not amod:
				amod = mod
			iprint("search_imports:", word, 'in mod', amod)
			for line in universe.load_imports(amod):
				#iprint('\t'+line)
				if word in line.split():
					iprint('Found import line:', repr(line))
					self.imports[word] = line
					return True
			return False


		#Use name to find function
		iprint('\n')
		if name in self.words or name in self.imports:
			return True
		if mod is None:
			mod = self.mymod
		caller_mod = mod
		modvars = vars(mod)
		if name not in modvars:
			return False
		else:
			func = modvars[name]
		iprint("Name:", name, func)
		mod = inspect.getmodule(func)
		if not mod:
			mod = caller_mod
		iprint('Module:', mod)
		modname = universe.get_modname(mod)
		if modname in self.ignore:
			return False
		modvars = vars(mod)



		#If the name doesn't match, it's an alias
		if name != universe.get_func_name(func):
			alias_finder(name, mod)


		# If reached a default mod, return
		if modname in sys.builtin_module_names or mod.__file__.startswith('/usr/lib'):
			iprint("Mod is builtin:", mod)
			return search_imports(name, caller_mod)
		# Don't scrape builtins
		if inspect.isbuiltin(func):
			iprint("Skipping builtin:", func)
			return False
		if func == mod:
			return False

		# If it's a method of a class, get the whole class
		if inspect.ismethod(func):
			parent = universe.get_class_that_defined_method(func)
			if universe.get_func_name(parent) not in self.words:
				iprint("Processing method", func, "of", parent)
				iprint(func.__name__, '=', func)

				if hasattr(func, '__self__'):
					iprint("Detected", func.__name__, "is bound method")
					alias_finder(func.__name__, mod)
				func = parent
			else:
				iprint("Already processed:", parent)
				return False

		if not callable(func):
			iprint(name, 'is not a function')
			return alias_finder(name, mod)
		self.words[name] = func

		# Get code
		if func in self.functions:
			return False
		code = universe.getsource(func)
		self.functions[func] = code
		iprint("Loaded:", plural(len(code), 'line'), 'of code')
		self.loaded.setdefault(modname, []).append(len(code))


		# Get words from within function and process them:
		words = universe.undefined(func)
		if words:
			iprint('words =', words)
		for word in words:
			if word in self.words:
				continue

			if not self.follow:
				if word not in self.imports:
					if word not in self.words:
						search_imports(word, caller_mod)
			if self.follow:
				if not self.process(word, mod=mod, level=level+1):
					if word not in self.words:
						search_imports(word, caller_mod)
		return True


	def get_code_words(self, filename, common_imports):
		print("\n\nProcessing:", filename)
		members = dict(inspect.getmembers(self.mymod))

		# Read through every line in the source code file, branching into the imports for more functions
		if '*' in common_imports:
			gen = iter(universe.scrape_wildcard(filename, members).keys())
		else:
			gen = iter(common_imports)

		for word in gen:
			word = word.strip(',')
			self.process(word, self.mymod)
		return self.functions

	def process_words(self, words):
		for word in words:
			self.process(word, self.mymod)
		return self.functions




################################################################################

def show_loc(proc):
	print('Lines of code copied from each module:')
	out = []
	for mod, val in sorted(proc.loaded.items()):
		out.append([(mod + ':'), str(sum(val)) + ' loc', 'in', str(len(val)) + ' functions'])
	auto_cols(out, space=2)


def main():
	args = get_args()
	mymod = universe.load_mod(args.mymod)
	modname = universe.get_modname(mymod)
	members = dict(inspect.getmembers(mymod))
	output_name = args.output_name.rstrip('.py')
	if output_name == 'same':
		output_name = modname
	filenames = args.filenames


	if args.onefile:
		filename = filenames[0]
		output_filename = os.path.join(args.output_dir, os.path.basename(filename))
	else:
		output_filename = os.path.join(args.output_dir, output_name + '.py')
	if samepath(output_filename, *filenames):
		error("Cannot overwrite self!")
	mkdir('/tmp/Star_Wrangler')

	print(modname, 'functions:')
	auto_cols([(name, str(func).replace('\n', ' ')) for name, func in sorted(members.items())], crop={1:200})
	print("\n")

	# Generate dict of required functions and their code
	filename = 'output'			# Default filename
	functions = odict()         # Dict of function names to code
	file_functions = dict()     # Dict filenames to function dicts
	file_imports = dict()       # Dict of filenames to import lists
	proc = Processor(mymod, max_level=args.max_level, follow=not args.nofollow, ignore=args.ignore)
	if args.functions:
		functions = proc.process_words(args.functions)
	else:
		for filename in filenames:
			line_nums = set()
			imports = []
			with open(filename) as f:
				source = f.read()
				# Go through file source and remove "import modname"
				terms = args.modnames if args.modnames else [modname,]
				for num, line in universe.scrape_imports(source):
					# if modname in line:
					if any(name in line for name in terms):
						print(line)
						line_nums.add(num)
						imports.append(re.sub('.*import ', '', line))
			if not imports:
				warn("Could not find any common imports in", filename, "for module name:", modname, delay=0)
			else:
				file_imports[filename] = imports
				imports = [re.sub(' as .*$', '', word) for word in imports]
				sub = proc.get_code_words(filename, imports)
				file_functions[filename] = sub
				for func in sub:
					if func not in functions:
						functions[func] = sub[func]

	if not functions:
		print("No functions discovered")
		sys.exit(0)


	print('\n' * 5)
	print("Done. Outputting to file:", output_filename)
	print('#' * 80, '\n')
	output = []

	def owl(*args):
		"Output write lines"
		output.append(' '.join(args))

	# Header
	if not args.onefile:
		owl("#!/usr/bin/python3")
		owl(shared.HEADER.strip())
	if args.onefile:
		owl(shared.HEADER.replace('file', 'section').strip())

	# Write import lines to top of the file
	owl('')
	func_names = functions.keys()
	for line in sorted(proc.imports.values(), key=len):
		words = re.sub('.* import ', '', line).split()
		if not any([word in func_names for word in words]):
			owl(line)
		else:
			print("Skipping locally referenced import line:", line)
	if proc.imports:
		owl("\n")

	# Functions
	for code in reversed(functions.values()):
		owl('\n'.join(code))
		owl('\n')

	#Aliases
	for line in set(proc.aliases.values()):
		owl(line)

	# Put it all together and output
	if args.onefile:
		ie = max(line_nums)
		source = source.splitlines()
		for num in line_nums:
			source.pop(num)
		output = source[:ie] + ['#' * 80] + output + ['#' * 80, '', ''] + source[ie:]
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

	if len(proc.loaded) > 1:
		print('\n')
		show_loc(proc)

	# Finished
	print('\n')
	print(rfs(os.path.getsize(output_filename)), 'of code saved to', output_filename)
	qrun('chmod', '+x', output_filename)
	print("\nCopy to script directory with:")
	print('cp', output_filename,
		  os.path.join(os.path.dirname(filename), os.path.basename(output_filename)))


if __name__ == "__main__":
	main()
