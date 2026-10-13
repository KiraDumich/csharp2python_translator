from typing import Dict, List, Optional, Set, Tuple

from parser import ASTNode, Symbol, SymbolKind, SymbolTable


class SemanticAnalyzer:
    # Матрица совместимости: целевой тип -> допустимые исходные типы.
    # Строки для byte, long и char дополняют таблицу из документации.
    COMPATIBLE = {
        "int": {"int", "byte"},
        "double": {"int", "float", "double", "byte", "long"},
        "float": {"int", "float", "byte", "long"},
        "string": {"string", "null"},
        "bool": {"bool"},
        "long": {"long", "int", "byte"},
        "byte": {"byte"},
        "char": {"char"},
    }

    NUMERIC_RANK = {"byte": 0, "int": 1, "long": 2, "float": 3, "double": 4}
    INTEGER_TYPES = {"byte", "int", "long"}
    LITERAL_SUFFIXES = {"f": "float", "d": "double", "l": "long"}

    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
        self.errors = []
        self.warnings = []
        self.current_method_return_type = None

        self.class_name: Optional[str] = None
        self.methods: Dict[str, Tuple[str, List[str]]] = {}
        # Стек областей локальных имён: тело метода и вложенные блоки
        self.local_scopes: List[Set[str]] = []
        self.position = (0, 0)

    def analyze(self, ast: ASTNode):
        for child in ast.children:
            if child.type == "ClassDeclaration":
                self.analyze_class(child)
        return ast

    def analyze_class(self, node: ASTNode):
        self.class_name = node.value
        self.symbol_table.enter_scope(self.class_name)

        body = self.find_child(node, "ClassBody")
        members = [m for m in (body.children if body else []) if m.type != "Comment"]

        if not members:
            self.warnings.append(f"Предупреждение: тело класса '{self.class_name}' "
                                 f"не содержит объявлений полей и методов")

        # Сигнатуры собираются заранее: метод можно вызвать до его объявления
        declared_members = {}
        for member in members:
            self.position = (member.line, member.column)
            if member.type == "MethodDeclaration":
                name = member.value
                if name not in self.methods:
                    params = self.find_child(member, "Parameters")
                    param_types = [p.children[0].value for p in (params.children if params else [])]
                    self.methods[name] = (member.children[0].value, param_types)
            else:
                name = self.find_child(member, "Identifier").value

            if name not in declared_members:
                declared_members[name] = member.type
            elif member.type == declared_members[name] == "MethodDeclaration":
                self.error("SE4", f"повторное объявление идентификатора '{name}': "
                                  f"перегрузка методов не поддерживается")
            else:
                self.error("SE4", f"повторное объявление идентификатора '{name}'")

        for member in members:
            self.local_scopes = []
            self.position = (member.line, member.column)
            if member.type == "MethodDeclaration":
                self.analyze_method(member)
            else:
                self.analyze_declaration(member)

        self.symbol_table.exit_scope()

    def analyze_method(self, node: ASTNode):
        self.position = (node.line, node.column)
        self.current_method_return_type = node.children[0].value
        self.symbol_table.enter_scope(f"{self.class_name}.{node.value}")
        self.local_scopes = [set()]

        params = self.find_child(node, "Parameters")
        for param in (params.children if params else []):
            self.declare_local(param.value)

        body = self.find_child(node, "MethodBody")
        statements = body.children if body else []
        for stmt in statements:
            self.analyze_statement(stmt)

        if self.current_method_return_type != "void" and not self.always_returns(statements):
            self.position = (node.line, node.column)
            self.error("SE2", f"несоответствие типа возврата: метод '{node.value}' типа "
                              f"{self.current_method_return_type} возвращает значение не на всех путях выполнения")

        self.symbol_table.exit_scope()
        self.local_scopes = []
        self.current_method_return_type = None

    def always_returns(self, statements: List[ASTNode]) -> bool:
        for stmt in statements:
            if stmt.type == "ReturnStatement":
                return True
            if stmt.type == "BlockStatement" and self.always_returns(stmt.children):
                return True
            if (stmt.type == "IfStatement" and len(stmt.children) == 3
                    and self.always_returns([stmt.children[1]]) and self.always_returns([stmt.children[2]])):
                return True
            if stmt.type == "WhileStatement" and stmt.children[0].value == "true":
                return True
        return False

    def analyze_statement(self, node: ASTNode):
        if node.type == "Comment":
            return

        self.position = (node.line, node.column)

        if node.type == "LocalDeclarationStatement":
            self.analyze_declaration(node)
        elif node.type == "AssignmentStatement":
            self.analyze_assignment(node)
        elif node.type == "ReturnStatement":
            self.analyze_return(node)
        elif node.type in ("IfStatement", "WhileStatement"):
            self.analyze_condition(node.children[0])
            for branch in node.children[1:]:
                self.analyze_statement(branch)
        elif node.type == "BlockStatement":
            self.symbol_table.enter_scope(node.scope)
            self.local_scopes.append(set())
            for stmt in node.children:
                self.analyze_statement(stmt)
            self.local_scopes.pop()
            self.symbol_table.exit_scope()
        elif node.type in ("UnaryIncrement", "UnaryDecrement"):
            operand_type = self.analyze_expression(node.children[0])
            if operand_type and operand_type not in self.NUMERIC_RANK:
                self.error("SE1", f"несовместимость типов: операция '{'++' if node.type == 'UnaryIncrement' else '--'}' "
                                  f"неприменима к типу {operand_type}")
        elif node.type == "ExpressionStatement":
            self.analyze_expression(node.children[0])

    def analyze_declaration(self, node: ASTNode):
        # Общий разбор для поля класса и локальной переменной
        declared_type = node.children[0].value
        name = node.children[1].value

        if len(node.children) > 2:
            expr = node.children[2]
            expr_type = self.analyze_expression(expr)
            if not self.is_compatible(declared_type, expr_type, expr):
                self.error("SE1", f"несовместимость типов: ожидался {declared_type}, найден {expr_type}")

        if node.type == "LocalDeclarationStatement":
            self.declare_local(name)

    def analyze_assignment(self, node: ASTNode):
        target_type = self.analyze_expression(node.children[0])

        if len(node.children) < 2:
            return
        expr = node.children[1]
        expr_type = self.analyze_expression(expr)

        if target_type and not self.is_compatible(target_type, expr_type, expr):
            self.error("SE1", f"несовместимость типов: ожидался {target_type}, найден {expr_type}")

    def analyze_return(self, node: ASTNode):
        expected = self.current_method_return_type

        if not node.children:
            if expected != "void":
                self.error("SE2", f"несоответствие типа возврата: ожидался {expected}, найден void")
            return

        expr = node.children[0]
        expr_type = self.analyze_expression(expr)
        if expected == "void":
            if expr_type:
                self.error("SE2", f"несоответствие типа возврата: ожидался void, найден {expr_type}")
        elif not self.is_compatible(expected, expr_type, expr):
            self.error("SE2", f"несоответствие типа возврата: ожидался {expected}, найден {expr_type}")

    def analyze_condition(self, node: ASTNode):
        cond_type = self.analyze_expression(node)
        if cond_type and cond_type != "bool":
            self.error("SE1", f"несовместимость типов: ожидался bool, найден {cond_type}")

    def analyze_expression(self, node: ASTNode) -> str:
        # Возвращает тип выражения; None означает, что тип определить не удалось
        # (ошибка уже зафиксирована), и зависящие от него проверки пропускаются
        result = self.infer_type(node)
        node.data_type = result
        return result

    def infer_type(self, node: ASTNode) -> Optional[str]:
        if node.type == "NumberLiteral":
            # Суффикс задаёт тип явно; без суффикса вещественный литерал имеет тип double
            value = node.value.lower()
            if value[-1] in self.LITERAL_SUFFIXES:
                return self.LITERAL_SUFFIXES[value[-1]]
            return "double" if "." in value or "e" in value else "int"

        if node.type == "StringLiteral":
            return "string"

        if node.type == "CharLiteral":
            return "char"

        if node.type == "BoolLiteral":
            return "bool"

        if node.type == "NullLiteral":
            return "null"

        if node.type == "Identifier":
            symbol = self.lookup(node.value)
            if not symbol or symbol.kind in (SymbolKind.METHOD, SymbolKind.CLASS):
                self.error("SE3", f"использование необъявленного идентификатора '{node.value}'")
                return None
            node.symbol = symbol
            return symbol.type

        if node.type == "MethodCall":
            return self.analyze_call(node)

        if node.type == "LogicalNot":
            operand_type = self.analyze_expression(node.children[0])
            return self.check_operands("!", [operand_type], operand_type == "bool", "bool")

        if node.type == "UnaryExpression":
            operand_type = self.analyze_expression(node.children[0])
            allowed = self.NUMERIC_RANK if node.value == "-" else self.INTEGER_TYPES
            return self.check_operands(node.value, [operand_type], operand_type in allowed,
                                       self.widest([operand_type]))

        if node.type in ("BinaryExpression", "LogicalAnd", "LogicalOr"):
            return self.analyze_binary(node)

        return None

    def analyze_binary(self, node: ASTNode) -> Optional[str]:
        op = node.value
        left = self.analyze_expression(node.children[0])
        right = self.analyze_expression(node.children[1])
        types = [left, right]
        numeric = left in self.NUMERIC_RANK and right in self.NUMERIC_RANK

        if op in ("&&", "||"):
            return self.check_operands(op, types, left == right == "bool", "bool")

        if op == "+" and "string" in types:
            return self.check_operands(op, types, "void" not in types, "string")

        if op in ("+", "-", "*", "/", "%"):
            return self.check_operands(op, types, numeric, self.widest(types))

        if op in ("<", ">", "<=", ">="):
            return self.check_operands(op, types, numeric or left == right == "char", "bool")

        if op in ("==", "!="):
            comparable = (numeric or (left == right and left != "void")
                          or set(types) == {"string", "null"})
            return self.check_operands(op, types, comparable, "bool")

        if op in ("&", "|", "^"):
            if left == right == "bool":
                return "bool"
            integer = left in self.INTEGER_TYPES and right in self.INTEGER_TYPES
            return self.check_operands(op, types, integer, self.widest(types))

        return None

    def analyze_call(self, node: ASTNode) -> Optional[str]:
        name = node.value
        args = node.children[0].children
        arg_types = [self.analyze_expression(arg) for arg in args]

        if self.is_local(name) or name not in self.methods:
            self.error("SE3", f"использование необъявленного идентификатора '{name}': метод не объявлен")
            return None

        node.symbol = self.lookup(name)
        return_type, param_types = self.methods[name]

        if len(args) != len(param_types):
            self.error("SE5", f"несоответствие числа аргументов при вызове '{name}': "
                              f"ожидалось {len(param_types)}, передано {len(args)}")
            return return_type

        for i, (param_type, arg_type, arg) in enumerate(zip(param_types, arg_types, args), 1):
            if not self.is_compatible(param_type, arg_type, arg):
                self.error("SE6", f"несоответствие типа аргумента {i} при вызове '{name}': "
                                  f"ожидался {param_type}, найден {arg_type}")

        return return_type

    def check_operands(self, op: str, types: List[Optional[str]], valid: bool,
                       result: Optional[str]) -> Optional[str]:
        if None in types:
            return None
        if not valid:
            self.error("SE1", f"несовместимость типов: операция '{op}' неприменима "
                              f"к {'типам' if len(types) > 1 else 'типу'} {' и '.join(types)}")
            return None
        return result

    def widest(self, types: List[Optional[str]]) -> Optional[str]:
        if any(t not in self.NUMERIC_RANK for t in types):
            return None
        # Арифметика над byte даёт int, как в C#
        return max(types + ["int"], key=lambda t: self.NUMERIC_RANK[t])

    def is_compatible(self, target: str, source: Optional[str], node: ASTNode) -> bool:
        if source is None:
            return True
        if target == "byte" and source == "int" and node.type == "NumberLiteral":
            return True
        return source in self.COMPATIBLE.get(target, set())

    def declare_local(self, name: str):
        # Имя не должно повторяться ни в текущем блоке, ни в охватывающих его
        if self.is_local(name):
            self.error("SE4", f"повторное объявление идентификатора '{name}'")
        self.local_scopes[-1].add(name)

    def is_local(self, name: str) -> bool:
        return any(name in scope for scope in self.local_scopes)

    def lookup(self, name: str) -> Optional[Symbol]:
        # Локальная переменная видна только после своего объявления
        if self.is_local(name):
            return self.symbol_table.lookup(name)
        for scope in (self.class_name, "global"):
            for symbol in self.symbol_table.symbols.get(scope, []):
                if symbol.name == name:
                    return symbol
        return None

    def find_child(self, node: ASTNode, node_type: str) -> Optional[ASTNode]:
        for child in node.children:
            if child.type == node_type:
                return child
        return None

    def error(self, code: str, message: str):
        line, column = self.position
        self.errors.append(f"Ошибка {code} [строка {line}, поз. {column + 1}]: {message}")
