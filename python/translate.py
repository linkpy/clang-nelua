
import sys
import pprint
from clang.cindex import Index, CursorKind, TypeKind


def gen_nelua_arglist(args):
	res = ""

	i = 0
	for arg in args:
		res += "a" + str(i) + ": " + arg + ", "
		i += 1

	if res != "":
		return res[:-2]

	return res


class AliasType:
	def __init__(self, n):
		self.name = n
		self.type = ""

		self.previous = None
		self.next = None

		self.noglobal = False
	
	def generate_nelua(self):
		return self.name + " = @" + self.type

class EnumType:
	def __init__(self, n):
		self.name = n
		self.values = {}
		self.simplified = False

		self.previous = None
		self.next = None

		self.noglobal = False
	

	def simplify(self):
		temp = {}

		prefix = None
		for name in self.values.keys():
			if prefix == None:
				if name.startswith(self.name + "_"):
					prefix = len(self.name) + 1
				
				else:
					prefix = name.find("_") + 1
			
			temp[name[prefix:]] = self.values[name]
		
		self.values = temp
		self.simplified = True
	
	def generate_nelua(self):
		if not self.simplified:
			self.simplify()

		res = self.name + " = @enum {\n"

		if len(self.values) > 0:
			for name in self.values.keys():
				res += "\t" + name + " = " + str(self.values[name]) + ",\n"

			res = res[:-2] + "\n"
		
		return res + "}"

class StructType:
	def __init__(self, n):
		self.name = n
		self.fields = []
		self.methods = []
		self.pointer = False

		self.previous = None
		self.next = None

		self.noglobal = False

	def generate_nelua(self):
		res = self.name + " = @"

		if self.pointer:
			res += "*"
		
		res += "record {\n"

		if len(self.fields) > 0:
			for field in self.fields:
				res += '\t' + field[0] + ': ' + field[1] + ',\n'
			
			return res[:-2] + '\n}\n'
		else:
			return res[:-1] + "}\n"


class FuncType:
	def __init__(self, n):
		self.name = n
		self.args = []
		self.ret_type = ""

		self.previous = None
		self.next = None

		self.noglobal = False
	
	def generate_nelua(self):
		res = self.name + " = @function(" + gen_nelua_arglist(self.args) + ")"
		
		if len(self.ret_type) > 0:
			res += ": " + self.ret_type
		
		return res

class FuncDecl(FuncType):
	def __init__(self, n):
		FuncType.__init__(self, n)
	
	def generate_nelua(self):
		res = "function " + self.name + "(" + gen_nelua_arglist(self.args) + ")"

		if len(self.ret_type) > 0:
			res += ": " + self.ret_type
		
		return res + " <cimport> end"

class MethodDecl(FuncType):
	def __init__(self, n, s):
		FuncType.__init__(self, s + ":" + n)
		self.method = n
		self.struct = s
		self.content = ""
		self.noglobal = True

	def generate_nelua(self):
		res = "function " + self.struct + ":" + self.method + "(" + gen_nelua_arglist(self.args) + ")"

		if len(self.ret_type) > 0:
			res += ": " + self.ret_type

		res += "\n"
		res += "\n".join(["\t" + l for l in self.content])
		return res + "\nend"


class Registery:
	def __init__(self):
		self.types = {}

		self.first_type = None
		self.last_type = None
	


	def register_type(self, t):
		if t.name in self.types:
			return

		self.types[t.name] = t
		t.previous = self.last_type

		if self.last_type != None:
			self.last_type.next = t
		
		self.last_type = t

		if self.first_type == None:
			self.first_type = t
	
	def get_types(self):
		res = []

		t = self.first_type

		while t != None:
			res.append(t)
			t = t.next
		
		return res
	



	

class Worker:
	def __init__(self, reg):
		self.file_path = ""
		self.registery = reg

		self.enum_orphans = []
		self.struct_orphans = []

		self.walk_curr_enum = None
		self.walk_curr_struct = None
	


	def work(self, index, path):
		tu = index.parse(path, [
			"-I/usr/lib/llvm-10/include/"
		])

		if not tu:
			raise Exception("couldn't get translation unit.")

		self.file_path = path
		self.walk(tu.cursor)



	def walk(self, cursor):
		for node in cursor.get_children():
			if node.location.file.name != self.file_path:
				continue

			kind = node.kind

			if kind == CursorKind.ENUM_DECL:
				self.walk_enum_decl(node)

			elif kind == CursorKind.ENUM_CONSTANT_DECL:
				self.walk_enum_constant_decl(node)	
			
			elif kind == CursorKind.TYPEDEF_DECL:
				self.walk_typedef_decl(node)
			
			elif kind == CursorKind.STRUCT_DECL:
				self.walk_struct_decl(node)
			
			elif kind == CursorKind.FIELD_DECL:
				self.walk_field_decl(node)
			
			elif kind == CursorKind.FUNCTION_DECL:
				self.walk_function_decl(node)
			
			else:
				self.walk(node)
	
	def walk_enum_decl(self, node):
		if len(node.spelling) > 0:
			self.walk_curr_enum = node.spelling
			self.registery.register_type(EnumType(node.spelling))

		self.walk(node)
		self.walk_curr_enum = None
	
	def walk_enum_constant_decl(self, node):
		if self.walk_curr_enum != None:
			self.registery.types[self.walk_curr_enum].values[node.spelling] = node.enum_value
		
		else:
			self.enum_orphans.append((node.spelling, node.enum_value))
	
	def walk_typedef_decl(self, node):
		children = [c for c in node.get_children()]


		if node.underlying_typedef_type.kind == TypeKind.POINTER:
			if len(children) > 1:
				# function type
				t = FuncType(node.spelling)
				t.ret_type = self.translate_type(children.pop(0).type)
				t.args = [self.translate_type(arg.type) for arg in children]
				self.registery.register_type(t)
				

			else: 
				# alias type
				t = AliasType(node.spelling)
				t.type = self.translate_type(node.underlying_typedef_type)
				self.registery.register_type(t)

			return

		if len(children) == 1:
			child = children[0]

			if child.kind == CursorKind.ENUM_DECL:
				
				if len(child.spelling) > 0:
					self.registery.types[node.spelling] = self.registery.types[child.spelling]
					self.registery.types.pop(child.spelling)
				
				else:
					self.registery.register_type(EnumType(node.spelling))

					for orphan in self.enum_orphans:
						self.registery.types[node.spelling].values[orphan[0]] = orphan[1]
					
					self.enum_orphans = []
			
			elif child.kind == CursorKind.STRUCT_DECL:
				
				if len(child.spelling) > 0:
					self.registery.types[node.spelling] = self.registery.types[child.spelling]
					self.registery.types.pop(child.spelling)
				
				else:
					t = StructType(node.spelling)
					t.fields = self.struct_orphans
					self.registery.register_type(t)
					self.struct_orphans = []
			
		else:
			print(node.spelling)
		
	def walk_struct_decl(self, node):
		if len(node.spelling) > 0:
			self.walk_curr_struct = node.spelling
			self.registery.register_type(StructType(node.spelling))

		self.walk(node)
		self.walk_curr_struct = None
	
	def walk_field_decl(self, node):
		if self.walk_curr_struct != None:
			self.registery.types[self.walk_curr_struct].fields.append((node.spelling, self.translate_type(node.type, True)))
		
		else:
			self.struct_orphans.append((node.spelling, self.translate_type(node.type, True)))
	
	def walk_function_decl(self, node):
		decl = FuncDecl(node.spelling)
		decl.ret_type = self.translate_type(node.type.get_result())
		decl.args = [self.translate_type(arg) for arg in node.type.argument_types()]
		self.registery.register_type(decl)
		
		# if decl.name.startswith("clang_dispose"):
		# 	arg0 = decl.args[0]
		# 	while arg0.startswith('*'): arg0 = arg0[1:]

		# 	meth = MethodDecl("__dispose", arg0)
		# 	meth.content = [decl.name + "(self)"]
		# 	self.registery.register_type(meth)

		# if len(decl.args) > 0:
		# 	arg0 = decl.args[0]
		# 	while arg0.startswith('*'): arg0 = arg0[1:]

		# 	if arg0 in self.registery.types:
		# 		meth = MethodDecl(decl.name[6:], arg0)

		# 		meth.method = meth.method.replace(arg0, "")

		# 		if arg0.startswith("CX"):
		# 			meth.method = meth.method.replace(arg0[2:], "")

		# 		if meth.method.startswith("_"):
		# 			meth.method = meth.method[1:]

		# 		if meth.method.endswith("_"):
		# 			meth.method = meth.method[:-2]

		# 		for i in range(1, len(decl.args)):
		# 			meth.args.append(decl.args[i])

		# 		meth.ret_type = decl.ret_type

		# 		if meth.ret_type:
		# 			if len(meth.args) == 0:
		# 				meth.content = ["return " + decl.name + "(self)"]

		# 			else:
		# 				meth.content = [
		# 					"return " + decl.name + "(self," + 
		# 						", ".join(['a' + str(i) for i in range(len(meth.args))])
		# 						+ ")"
		# 				]

		# 		else:
		# 			if len(meth.args) == 0:
		# 				meth.content = [decl.name + "(self)"]

		# 			else:
		# 				meth.content = [
		# 					decl.name + "(self," + 
		# 						", ".join(['a' + str(i) for i in range(len(meth.args))])
		# 						+ ")"
		# 				]					

		# 		self.registery.register_type(meth)



	def translate_type(self, t, tctx = True):
		if not tctx:
			tr = self._translate_type(t)

			if len(tr) == 0:
				return ""

			return "@" + tr
		
		return self._translate_type(t)

	def _translate_type(self, t):
		if t.kind == TypeKind.VOID:
			return ""

		elif t.kind == TypeKind.BOOL:
			return "boolean"

		elif t.kind == TypeKind.CHAR_U:
			return "cchar"
		
		elif t.kind == TypeKind.UCHAR:
			return 'cushar'
		
		elif t.kind == TypeKind.CHAR16:
			return 'uint16'
		
		elif t.kind == TypeKind.CHAR32:
			return 'uint32'
		
		elif t.kind == TypeKind.USHORT:
			return 'cushort'
		
		elif t.kind == TypeKind.UINT:
			return 'cuint'
		
		elif t.kind == TypeKind.ULONG:
			return 'culong'
		
		elif t.kind == TypeKind.ULONGLONG:
			return 'culong'
		
		elif t.kind == TypeKind.UINT128:
			return 'uint128'
		
		elif t.kind == TypeKind.CHAR_S:
			return 'cchar'
		
		elif t.kind == TypeKind.SCHAR:
			return 'cschar'
		
		elif t.kind == TypeKind.WCHAR:
			return '----'
		
		elif t.kind == TypeKind.SHORT:
			return 'cshort'
		
		elif t.kind == TypeKind.INT:
			return 'cint'
		
		elif t.kind == TypeKind.LONG:
			return 'clong'

		elif t.kind == TypeKind.LONGLONG:
			return 'clonglong'
		
		elif t.kind == TypeKind.INT128:
			return 'int128'
		
		elif t.kind == TypeKind.FLOAT:
			return 'float32'
		
		elif t.kind == TypeKind.DOUBLE:
			return 'float64'
		
		elif t.kind == TypeKind.LONGDOUBLE:
			return 'clongdouble'
		
		elif t.kind == TypeKind.FLOAT128:
			return 'float128'

		elif t.kind == TypeKind.POINTER:
			pt = t.get_pointee()
			tpt = self.translate_type(pt)

			if tpt == "cchar":
				return "cstring"

			if pt.kind == TypeKind.VOID:
				return "pointer"

			if pt.kind == TypeKind.FUNCTIONPROTO:
				return tpt

			return "*" + tpt

		elif t.kind == TypeKind.RECORD:
			if len(t.get_declaration().spelling) > 0:
				return t.get_declaration().spelling

			result = "record{ \n"

			for field in t.get_fields():
				result += '\t' + field.spelling + ': ' + self.translate_type(field.type) + ',\n'

			return result + '}'
	
		elif t.kind == TypeKind.ENUM:
			if len(t.spelling) > 0:
				return t.get_declaration().spelling

			return 'enum{}'
	
		elif t.kind == TypeKind.TYPEDEF:
			tdefn = t.get_typedef_name()

			if tdefn == "size_t":
				return "csize"

			return tdefn
		
		elif t.kind == TypeKind.FUNCTIONPROTO:
			result = "function("
			idx = 0

			for arg in t.argument_types():
				result += "a" + str(idx) + ': ' + self.translate_type(arg) + ', '
				idx += 1

			result = result[:-2] + ')'
			rtype = self.translate_type(t.get_result())

			if len(rtype) > 0 :
				result += ': ' + rtype

			return result
		
		elif t.kind == TypeKind.CONSTANTARRAY:
			return '[' + str(t.element_count) + ']' + self.translate_type(t.element_type)
		
		elif t.kind == TypeKind.ELABORATED:
			return self.translate_type(t.get_named_type())
		

		print("oops", t.spelling, t.kind, sep="\t")
		raise Exception("oops")

		
		

			



index = Index.create()

registery = Registery()

Worker(registery).work(index, "/usr/lib/llvm-10/include/clang-c/CXErrorCode.h")
Worker(registery).work(index, "/usr/lib/llvm-10/include/clang-c/CXString.h")
Worker(registery).work(index, "/usr/lib/llvm-10/include/clang-c/Index.h")


print("## linklib 'clang'")
print("global clang = @record{ }")

for t in registery.get_types():
	if t.noglobal:
		print(t.generate_nelua())
	else:
 		print("global " + t.generate_nelua())
