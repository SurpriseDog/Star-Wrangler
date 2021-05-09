'''Old version called list.used.functions.py that used ast to parse:

#!/usr/bin/python3
# Usage:  ./list.used.functions.py <main python file> <imported module name>
# List functions used by a module
# Use this to replace those forbidden star imports: "from mymodule import * ...

import ast
import inspect
import sys
import importlib
sys.path.append('.')
from common import *
tab = ' ' * 4  			# Output tabs for display



#Get arguments
if len(sys.argv) != 3:
	error("Expected 3 arguments")
filename = sys.argv[1]
arg = sys.argv[2].rstrip('.py').rstrip('.pyc')


# Import user given module
mymodule = importlib.import_module(arg)


# Get list of functions and classes from mymodule
funcs = set()
for f_name, f_type in inspect.getmembers(mymodule):
	if str(f_type)[1:].split(' ')[0] in ('function', 'class') and \
			inspect.getmodule(f_type) == mymodule:
		funcs.add(f_name)
print('Found functions in module:', funcs)


# Only include functions that are used by the main code
with open(filename) as f:
	code = ast.parse(f.read())
	words = {node.id for node in ast.walk(code) if isinstance(node, ast.Name)}
	print("\nFound words in script:", words)



#Print out list of matches
matches = ', '.join(sorted(words & funcs))
print("\nMatched:", matches)
print("")
out = 'from ' + mymodule.__name__ + ' import '
if len(out+matches) <= 80:
	print(out+matches)
else:
	print(out + '(')
	out = tab
	for word in matches.split():
		if len(out + word) > 80:
			print(out.rstrip())
			out = tab + word + ' '
		else:
			out += word + ' '
	print(out.rstrip() + ')')

'''
