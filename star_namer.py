#!/usr/bin/python3
# Replace star imports with something more useful
# Usage: ./star_namer.py <module_file> <script_filename>
# Requires pylint: https://www.pylint.org/#install

import os
import sys
import inspect

import universe
from sd.common import error, eprint
from sd.columns import indenter, auto_cols
from sd.easy_args import easy_parse


def main():
	if len(sys.argv) < 3:
		print("Usage: ./star_namer.py <module_file> <script_filenames...> --options...")
		sys.exit(1)
	args = [\
		["exclude", "", list],
		"Exclude any function found in these module names",
		["local", '', bool],
		"Don't list any functions outside of file",
		["actual", '', bool, False],
		"Print the actual module each function is found in",
		]
	positionals = [\
		["module"],
		"Module name to search through functions",
		["scripts", '', list],
		"Python scripts to scan through",
		]

	#Load the args:
	args = easy_parse(args, positionals)
	filenames = args.scripts
	for name in filenames:
		if not os.path.exists(name):
			error(name, "does not exist")


	mymod = universe.load_mod(args.module)
	modname = universe.get_modname(mymod)
	modvars = universe.get_members(args.module)
	print("Found defined variables in module", modname+':')
	out = [['Name:', 'Module:', 'Function:']]
	for name, func in modvars.items():
		out.append([name, universe.get_modname(inspect.getmodule(func)), func])
	auto_cols(out)
	print("\n")


	for filename in filenames:
		functions = universe.scrape_wildcard(filename, modvars)
		if len(filenames) > 1:
			print('\n')
			eprint(filename+':', '\n', v=2)

		if functions:
			out = dict()
			for name, func in functions.items():
				mod = universe.get_modname(inspect.getmodule(func))
				if mod in args.exclude:
					continue
				if args.local and mod != modname:
					continue

				mod = mod if args.actual else modname
				out.setdefault(mod, []).append(name)

			for mod, funcs in out.items():
				header = 'from ' + mod + ' import '
				for line in indenter(', '.join(funcs), header=header, wrap=80):
					print(line.rstrip(','))
		else:
			print("<no functions found>")

if __name__ == "__main__":
	main()
