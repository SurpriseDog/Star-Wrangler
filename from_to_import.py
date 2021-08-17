#!/usr/bin/python3
# Convert a python file with from import function_name to module.function_name
# Usage: from_to_import.py <script name> <modname>

import re
import sys
import universe

from sd.common import str_insert, query, sort_array

def convert(source, modname):
	"Swap from imports with module.name"
	found_modname_import = False

	# Get list of "from" imports
	nums = set()				# Line numbers
	words = set()
	print("\nFound Imports:")
	for lineno, line in universe.scrape_imports(source):
		if line.startswith('from ' + modname):
			word = line.split()[-1]
			nums.add(lineno)
			words.add(word)
			print(lineno, word)
		elif modname in line:
			found_modname_import = True
	if not words:
		return None


	print("\nGetting list of currently undefined words...")
	undefined = list(universe.get_undefined(source))
	print("Found:", len(undefined))

	# Strip "from" lines
	print("\nRemoving 'from' lines:")
	source = source.splitlines()
	for lineno in sorted(list(nums), reverse=True):
		line = source.pop(lineno)
		print("Removed:", line)


	# Insert a import
	if not found_modname_import:
		source.insert(min(nums), 'import ' + modname)


	print("\nGetting list of new undefined words...")
	matches = []
	for item in universe.get_undefined('\n'.join(source)):
		if item not in undefined:
			match = [item['line'] - 1, item['column']]
			matches.append(match)
	print("Found:", len(matches))
	if not matches:
		return None


	# Go through the source code in reverse order inserting modname
	sort_array(matches, reverse=True)
	print("\nReplacements:")
	for num, column in matches:
		print(num, source[num].lstrip())
		source[num] = str_insert(source[num], column, modname + '.')
		print(num, source[num].lstrip(), '\n')

	return '\n'.join(source)


def main():
	if len(sys.argv) == 3:
		filename = sys.argv[1]
		modname = sys.argv[2].replace('/', '.')
		modname = re.sub('\.py$', '', modname)
	else:
		print("Usage: from_to_import.py <script name> <modname>")
		sys.exit(1)

	with open(filename) as f:
		source = f.read()
		source = convert(source, modname)

	if not source:
		print("Could not find anything to convert, check your spelling and try again.")
		sys.exit(1)

	if query('Save?'):
		with open(filename, 'w') as f:
			f.write(source)


if __name__ == "__main__":
	main()
