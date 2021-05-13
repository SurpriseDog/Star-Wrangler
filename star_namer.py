#!/usr/bin/python3
# Replace star imports with something more useful
# Usage: ./star_namer.py <module_file> <script_filename>
# Requires pylint: https://www.pylint.org/#install

import os
import sys
import types
import importlib.util
from inspect import getmembers, isfunction

import shared

from star_common import quickrun, indenter, search_list, warn, error

def check_pylint():
	# Check pylint version:
	pylint = shared.PYLINT

	if not os.path.exists(pylint):
		warn("Pylint path does not exist:", pylint)
		print("Please install: https://www.pylint.org/#install")
		print("and then set the correct path in shared.py")
		sys.exit(1)

	version = quickrun(pylint, '--version')
	version = search_list('pylint', version, getfirst=True).split()[-1].split('.')[:2]
	if list(map(int, version)) < [2, 4]:
		error("Pylint must be at least version 2.4")

	return pylint


def scrape_wildcard(filename, modvars):
	"Get variables imported from module in wild * import"
	err = "W0614: Unused import "
	unused = []
	for line in quickrun([PYLINT, filename]):
		if err in line:
			unused.append(line.split(err)[1].split()[0])

	out = dict()
	for name in set(modvars) - set(unused):
		if not name.startswith('__'):
			func = modvars[name]
			if not isinstance(func, types.ModuleType):
				out[name] = modvars[name]
	return out

def load_mod(filename, execute=True):
	"Load a module given a filename"
	modname = os.path.basename(filename)
	modname = os.path.splitext(modname)[0]
	spec = importlib.util.spec_from_file_location("mymod", filename)
	mymod = importlib.util.module_from_spec(spec)
	if execute:
		spec.loader.exec_module(mymod)
	return mymod


def main():
	mymod = load_mod(sys.argv[1])
	modname = mymod.__name__
	modvars = dict(getmembers(mymod, isfunction))
	print("Found defined variables in module", modname+':')
	for key, val in modvars.items():
		print(key, val)
	print("\n")


	filename = sys.argv[2]
	header = 'from ' + modname + ' import '
	functions = ', '.join(scrape_wildcard(filename, modvars))
	for line in indenter(functions, header=header, wrap=80):
		print(line.rstrip(','))


if __name__ == "__main__":
	PYLINT = check_pylint()
	main()
