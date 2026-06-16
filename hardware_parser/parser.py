"""
Parser for HWDL Compiler

Implements recursive descent parser following the EBNF grammar in §3.
"""

from typing import List, Optional, Union
from .lexer import Token, TokenKind, lex
from .ast_nodes import *
from .diagnostics import DiagList, Severity


class Parser:
    """Recursive descent parser for HWDL."""

    def __init__(self, tokens: List[Token], diags: DiagList, source: str):
        self.tokens = tokens
        self.diags = diags
        self.source = source
        self.pos = 0

    @staticmethod
    def from_source(text: str, filename: str = "<stdin>") -> tuple['Parser', DiagList]:
        """Create a parser from source text."""
        diags = DiagList()
        tokens = lex(text, filename)
        
        for token in tokens:
            if token.kind == TokenKind.MISMATCH:
                diags.error(
                    "E001",
                    token.loc,
                    f"Unexpected character '{token.value}'",
                    hint="Check source code for invalid characters"
                )
        
        return Parser(tokens, diags, filename), diags

    def current_token(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]

    def peek_token(self, offset: int = 1) -> Token:
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]

    def consume(self, expected: Optional[TokenKind] = None) -> Token:
        token = self.current_token()
        if expected and token.kind != expected:
            self.diags.error("E100", token.loc, f"Expected {expected.value} but found {token.kind.value}")
        if token.kind != TokenKind.EOF:
            self.pos += 1
        return token

    def expect(self, kind: TokenKind) -> Token:
        token = self.current_token()
        if token.kind != kind:
            self.diags.error("E100", token.loc, f"Expected {kind.value} but found {token.kind.value}")
        return self.consume(kind)

    def match(self, *kinds: TokenKind) -> bool:
        return self.current_token().kind in kinds

    def skip_to_recovery_point(self) -> None:
        while self.current_token().kind not in (TokenKind.SEMICOLON, TokenKind.RBRACE, TokenKind.EOF):
            self.consume()
        if self.match(TokenKind.SEMICOLON):
            self.consume()

    def parse_file(self) -> File:
        if not self.match(TokenKind.KW_HWDL):
            self.diags.error("E402", self.current_token().loc, "version_decl must be first")
        version = self.parse_version_decl()
        items = []
        while self.current_token().kind != TokenKind.EOF:
            decl = self.parse_top_decl()
            if decl: items.append(decl)
            else:
                if self.current_token().kind == TokenKind.EOF: break
                self.skip_to_recovery_point()
        return File(version, items, self.source, version.loc)

    def parse_version_decl(self) -> VersionDecl:
        loc = self.current_token().loc
        if not self.match(TokenKind.KW_HWDL): return VersionDecl(1, 0, loc)
        self.expect(TokenKind.KW_HWDL)
        version_token = self.expect(TokenKind.VERSION)
        parts = version_token.value.split(".")
        major = int(parts[0]); minor = int(parts[1]) if len(parts) > 1 else 0
        self.expect(TokenKind.SEMICOLON)
        return VersionDecl(major, minor, loc)

    def parse_top_decl(self) -> Optional[TopDecl]:
        if self.match(TokenKind.KW_PART): return self.parse_part_decl()
        if self.match(TokenKind.KW_POWER): return self.parse_power_decl()
        if self.match(TokenKind.KW_MODULE): return self.parse_module_decl()
        if self.match(TokenKind.KW_TARGET): return self.parse_target_decl()
        if self.match(TokenKind.KW_NET): return self.parse_net_decl()
        self.diags.error("E100", self.current_token().loc, "Expected top-level decl")
        return None

    def parse_part_decl(self) -> PartDecl:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_PART)
        name = self.expect(TokenKind.STRING).value
        self.expect(TokenKind.LBRACE)
        attrs = []; pins = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            if self.match(TokenKind.KW_PINS): pins.extend(self.parse_pins_block())
            else: attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return PartDecl(name, attrs, pins, loc)

    def parse_pins_block(self) -> List[PinStmt]:
        self.expect(TokenKind.KW_PINS); self.expect(TokenKind.LBRACE)
        pins = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            pins.append(self.parse_pin_stmt())
        self.expect(TokenKind.RBRACE)
        return pins

    def parse_pin_stmt(self) -> PinStmt:
        loc = self.current_token().loc
        name = self.expect(TokenKind.IDENT).value
        self.expect(TokenKind.COLON)
        dir_tok = self.consume()
        if dir_tok.kind not in (TokenKind.PINDIR_POWER_IN, TokenKind.PINDIR_POWER_OUT, TokenKind.PINDIR_POWER_GND, TokenKind.PINDIR_INPUT, TokenKind.PINDIR_OUTPUT, TokenKind.PINDIR_BIDIR, TokenKind.PINDIR_PASSIVE, TokenKind.PINDIR_OPEN_DRAIN, TokenKind.PINDIR_NO_CONNECT):
             self.diags.error("E100", dir_tok.loc, "Expected pin direction")
        self.expect(TokenKind.SEMICOLON)
        return PinStmt(name, dir_tok.value, loc)

    def parse_power_decl(self) -> PowerDecl:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_POWER); name = self.expect(TokenKind.IDENT).value
        self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return PowerDecl(name, attrs, loc)

    def parse_module_decl(self) -> ModuleDecl:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_MODULE); name = self.expect(TokenKind.IDENT).value
        self.expect(TokenKind.LBRACE)
        items = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            if self.match(TokenKind.KW_CONSTRAINT): items.append(self.parse_constraint_block())
            elif self.match(TokenKind.KW_PLACEMENT): items.append(self.parse_placement_block())
            elif self.match(TokenKind.KW_ROUTING): items.append(self.parse_routing_block())
            elif self.match(TokenKind.KW_VALIDATE): items.append(self.parse_validate_block())
            elif self.match(TokenKind.KW_SIMULATE): items.append(self.parse_simulate_block())
            elif self.match(TokenKind.KW_NET): items.append(self.parse_net_decl())
            elif self.match(TokenKind.KW_CONNECT): items.append(self.parse_connect_stmt())
            elif self.match(TokenKind.IDENT): items.append(self.parse_instance_decl())
            else:
                self.diags.error("E100", self.current_token().loc, "Unexpected module item")
                self.skip_to_recovery_point()
        self.expect(TokenKind.RBRACE)
        return ModuleDecl(name, items, loc)

    def parse_net_decl(self) -> NetDecl:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_NET); name = self.expect(TokenKind.IDENT).value
        self.expect(TokenKind.SEMICOLON)
        return NetDecl(name, loc)

    def parse_instance_decl(self) -> InstanceDecl:
        loc = self.current_token().loc
        ref = self.expect(TokenKind.IDENT).value; self.expect(TokenKind.COLON)
        part = self.expect(TokenKind.STRING).value
        attrs = []
        if self.match(TokenKind.LBRACE):
            self.consume()
            while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
            self.expect(TokenKind.RBRACE)
        self.expect(TokenKind.SEMICOLON)
        return InstanceDecl(ref, part, attrs, loc)

    def parse_connect_stmt(self) -> ConnectStmt:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_CONNECT); src = self.parse_endpoint()
        self.expect(TokenKind.ARROW); dst = self.parse_endpoint()
        self.expect(TokenKind.SEMICOLON)
        return ConnectStmt(src, dst, loc)

    def parse_endpoint(self) -> Endpoint:
        loc = self.current_token().loc
        if self.match(TokenKind.KW_POWER):
            self.consume(); self.expect(TokenKind.DOT)
            return PowerRef(self.expect(TokenKind.IDENT).value, loc)
        if self.match(TokenKind.IDENT):
            first = self.expect(TokenKind.IDENT).value
            if self.match(TokenKind.DOT):
                self.consume(); return PinRef(first, self.expect(TokenKind.IDENT).value, loc)
            return NetRef(first, loc)
        self.diags.error("E100", loc, "Expected endpoint")
        return NetRef("", loc)

    def parse_constraint_block(self) -> ConstraintBlock:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_CONSTRAINT); self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return ConstraintBlock(attrs, loc)

    def parse_placement_block(self) -> PlacementBlock:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_PLACEMENT); self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return PlacementBlock(attrs, loc)

    def parse_routing_block(self) -> RoutingBlock:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_ROUTING); self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return RoutingBlock(attrs, loc)

    def parse_validate_block(self) -> ValidateBlock:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_VALIDATE); self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return ValidateBlock(attrs, loc)

    def parse_simulate_block(self) -> SimulateBlock:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_SIMULATE); self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return SimulateBlock(attrs, loc)

    def parse_target_decl(self) -> TargetDecl:
        loc = self.current_token().loc
        self.expect(TokenKind.KW_TARGET); name = self.expect(TokenKind.IDENT).value
        self.expect(TokenKind.LBRACE)
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF): attrs.append(self.parse_attr_stmt())
        self.expect(TokenKind.RBRACE)
        return TargetDecl(name, attrs, loc)

    def parse_attr_stmt(self) -> AttrStmt:
        loc = self.current_token().loc
        key = self.parse_attr_key(); self.expect(TokenKind.COLON)
        val = self.parse_attr_val(); self.expect(TokenKind.SEMICOLON)
        return AttrStmt(key, val, loc)

    def parse_attr_key(self) -> AttrKey:
        loc = self.current_token().loc; parts = [self.expect(TokenKind.IDENT).value]
        if self.match(TokenKind.DOT): self.consume(); parts.append(self.expect(TokenKind.IDENT).value)
        return AttrKey(parts, loc)

    def parse_attr_val(self) -> AttrVal:
        loc = self.current_token().loc
        if self.match(TokenKind.STRING): return StringVal(self.expect(TokenKind.STRING).value, loc)
        if self.match(TokenKind.KW_TRUE, TokenKind.KW_FALSE):
            tok = self.consume(); return BoolVal(tok.kind == TokenKind.KW_TRUE, loc)
        if self.match(TokenKind.LBRACKET): return self.parse_list_val()
        if self.match(TokenKind.NUMBER): return self.parse_phys_or_range_val()
        if self.match(TokenKind.IDENT): return IdentVal(self.expect(TokenKind.IDENT).value, loc)
        self.diags.error("E100", loc, "Expected attr value")
        return StringVal("", loc)

    def parse_phys_or_range_val(self) -> Union[PhysVal, RangeVal, IntVal]:
        loc = self.current_token().loc
        num_tok = self.expect(TokenKind.NUMBER); val = float(num_tok.value)
        unit = self.expect(TokenKind.UNIT).value if self.match(TokenKind.UNIT) else ""
        if not unit:
             if "." not in num_tok.value and "e" not in num_tok.value.lower():
                  low = IntVal(int(val), loc)
             else:
                  low = PhysVal(val, "", loc)
        else:
             low = PhysVal(val, unit, loc)
        
        if self.match(TokenKind.KW_TO):
            self.consume()
            num_tok2 = self.expect(TokenKind.NUMBER); val2 = float(num_tok2.value)
            unit2 = self.expect(TokenKind.UNIT).value if self.match(TokenKind.UNIT) else ""
            high = PhysVal(val2, unit2, num_tok2.loc)
            if isinstance(low, IntVal): low = PhysVal(float(low.value), "", low.loc)
            return RangeVal(low, high, loc)
        return low

    def parse_list_val(self) -> ListVal:
        loc = self.current_token().loc; self.expect(TokenKind.LBRACKET); items = []
        while not self.match(TokenKind.RBRACKET, TokenKind.EOF):
            items.append(self.parse_attr_val())
            if self.match(TokenKind.COMMA): self.consume()
        self.expect(TokenKind.RBRACKET)
        return ListVal(items, loc)
