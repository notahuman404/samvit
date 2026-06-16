"""
Parser for HWDL Compiler

Implements recursive descent parser following the EBNF grammar.
"""

from typing import List, Optional, Union
from lexer import Token, TokenKind, Lexer
from ast_nodes import *
from diagnostics import DiagList, Severity


class Parser:
    """Recursive descent parser for HWDL."""

    def __init__(self, tokens: List[Token], diags: DiagList):
        self.tokens = tokens
        self.diags = diags
        self.pos = 0

    @staticmethod
    def from_source(text: str, filename: str = "<stdin>") -> tuple['Parser', DiagList]:
        """Create a parser from source text."""
        diags = DiagList()
        lexer = Lexer(text, filename)
        tokens = lexer.tokenize()
        
        # Check for lexer errors
        for token in tokens:
            if token.kind == TokenKind.ERROR:
                diags.error(
                    "E001",
                    token.loc,
                    f"Unexpected character '{token.text}'",
                    hint="Check source code for invalid characters"
                )
        
        return Parser(tokens, diags), diags

    def current_token(self) -> Token:
        """Get the current token without consuming it."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def peek_token(self, offset: int = 1) -> Token:
        """Peek ahead by offset tokens."""
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def consume(self, expected: Optional[TokenKind] = None) -> Token:
        """Consume and return the current token."""
        token = self.current_token()
        
        if expected and token.kind != expected:
            self.diags.error(
                "E100",
                token.loc,
                f"Expected {expected.value} but found {token.kind.value}",
                hint=f"Got '{token.text}'"
            )
        
        if token.kind != TokenKind.EOF:
            self.pos += 1
        
        return token

    def expect(self, kind: TokenKind) -> Token:
        """Consume a token of the expected kind."""
        token = self.current_token()
        if token.kind != kind:
            self.diags.error(
                "E100",
                token.loc,
                f"Expected {kind.value} but found {token.kind.value}",
                hint=f"Got '{token.text}'"
            )
        return self.consume(kind)

    def match(self, *kinds: TokenKind) -> bool:
        """Check if current token matches any of the given kinds."""
        return self.current_token().kind in kinds

    def skip_to_recovery_point(self) -> None:
        """Skip tokens until we find ; or } for error recovery."""
        while self.current_token().kind not in (TokenKind.SEMICOLON, TokenKind.RBRACE, TokenKind.EOF):
            self.consume()

    def parse_file(self) -> File:
        """Parse the entire file."""
        version = self.parse_version_decl()
        
        if self.diags.has_errors():
            return File(version, [], version.loc)
        
        items = []
        while self.current_token().kind != TokenKind.EOF:
            if self.current_token().kind in (
                TokenKind.KW_PART,
                TokenKind.KW_POWER,
                TokenKind.KW_MODULE,
                TokenKind.KW_TARGET,
            ):
                items.append(self.parse_top_decl())
            else:
                self.diags.error(
                    "E100",
                    self.current_token().loc,
                    f"Unexpected top-level construct: {self.current_token().text}",
                )
                self.skip_to_recovery_point()
        
        return File(version, items, version.loc)

    def parse_version_decl(self) -> VersionDecl:
        """Parse version declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_HWDL)
        
        version_token = self.expect(TokenKind.VERSION)
        parts = version_token.text.split(".")
        major = int(parts[0]) if parts[0].isdigit() else 1
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        
        self.expect(TokenKind.SEMICOLON)
        
        return VersionDecl(major, minor, loc)

    def parse_top_decl(self) -> TopDecl:
        """Parse a top-level declaration."""
        if self.match(TokenKind.KW_PART):
            return self.parse_part_decl()
        elif self.match(TokenKind.KW_POWER):
            return self.parse_power_decl()
        elif self.match(TokenKind.KW_MODULE):
            return self.parse_module_decl()
        elif self.match(TokenKind.KW_TARGET):
            return self.parse_target_decl()
        else:
            self.diags.error(
                "E100",
                self.current_token().loc,
                f"Expected part, power, module, or target, got {self.current_token().text}",
            )
            self.skip_to_recovery_point()
            return None

    def parse_part_decl(self) -> PartDecl:
        """Parse a part declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_PART)
        
        name_token = self.expect(TokenKind.STRING)
        name = name_token.text
        
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        pins = None
        
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            if self.match(TokenKind.KW_PINS):
                pins = self.parse_pins_block()
            else:
                attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        
        return PartDecl(name, attrs, pins, loc)

    def parse_pins_block(self) -> List[PinStmt]:
        """Parse a pins block."""
        self.expect(TokenKind.KW_PINS)
        self.expect(TokenKind.LBRACE)
        
        pins = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            pins.append(self.parse_pin_stmt())
        
        self.expect(TokenKind.RBRACE)
        return pins

    def parse_pin_stmt(self) -> PinStmt:
        """Parse a pin statement."""
        loc = self.current_token().loc
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.COLON)
        
        direction_token = self.current_token()
        if direction_token.kind == TokenKind.PINDIR_POWER_IN:
            direction = PinDirection.POWER_IN
        elif direction_token.kind == TokenKind.PINDIR_POWER_OUT:
            direction = PinDirection.POWER_OUT
        elif direction_token.kind == TokenKind.PINDIR_POWER_GND:
            direction = PinDirection.POWER_GND
        elif direction_token.kind == TokenKind.PINDIR_INPUT:
            direction = PinDirection.INPUT
        elif direction_token.kind == TokenKind.PINDIR_OUTPUT:
            direction = PinDirection.OUTPUT
        elif direction_token.kind == TokenKind.PINDIR_BIDIR:
            direction = PinDirection.BIDIR
        elif direction_token.kind == TokenKind.PINDIR_PASSIVE:
            direction = PinDirection.PASSIVE
        elif direction_token.kind == TokenKind.PINDIR_OPEN_DRAIN:
            direction = PinDirection.OPEN_DRAIN
        elif direction_token.kind == TokenKind.PINDIR_NO_CONNECT:
            direction = PinDirection.NO_CONNECT
        else:
            self.diags.error("E100", direction_token.loc, f"Expected pin direction, got {direction_token.text}")
            direction = PinDirection.PASSIVE
        
        self.consume()
        self.expect(TokenKind.SEMICOLON)
        
        return PinStmt(name, direction, loc)

    def parse_power_decl(self) -> PowerDecl:
        """Parse a power domain declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_POWER)
        
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        
        return PowerDecl(name, attrs, loc)

    def parse_module_decl(self) -> ModuleDecl:
        """Parse a module declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_MODULE)
        
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.LBRACE)
        
        items = []
        constraint = None
        placement = None
        routing = None
        validate = None
        simulate = None
        
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            if self.match(TokenKind.KW_CONSTRAINT):
                constraint = self.parse_constraint_block()
            elif self.match(TokenKind.KW_PLACEMENT):
                placement = self.parse_placement_block()
            elif self.match(TokenKind.KW_ROUTING):
                routing = self.parse_routing_block()
            elif self.match(TokenKind.KW_VALIDATE):
                validate = self.parse_validate_block()
            elif self.match(TokenKind.KW_SIMULATE):
                simulate = self.parse_simulate_block()
            elif self.match(TokenKind.KW_NET):
                items.append(self.parse_net_decl())
            elif self.match(TokenKind.KW_CONNECT):
                items.append(self.parse_connect_stmt())
            elif self.match(TokenKind.IDENT):
                items.append(self.parse_instance_decl())
            else:
                self.diags.error(
                    "E100",
                    self.current_token().loc,
                    f"Unexpected module item: {self.current_token().text}",
                )
                self.skip_to_recovery_point()
        
        self.expect(TokenKind.RBRACE)
        
        return ModuleDecl(name, items, constraint, placement, routing, validate, simulate, loc)

    def parse_net_decl(self) -> NetDecl:
        """Parse a net declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_NET)
        
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.SEMICOLON)
        
        return NetDecl(name, loc)

    def parse_instance_decl(self) -> InstanceDecl:
        """Parse an instance declaration."""
        loc = self.current_token().loc
        
        ref_name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.COLON)
        
        part_name = self.expect(TokenKind.STRING).text
        
        attrs = None
        if self.match(TokenKind.LBRACE):
            self.consume()
            attrs = []
            while not self.match(TokenKind.RBRACE, TokenKind.EOF):
                attrs.append(self.parse_attr_stmt())
            self.expect(TokenKind.RBRACE)
        
        self.expect(TokenKind.SEMICOLON)
        
        return InstanceDecl(ref_name, part_name, attrs, loc)

    def parse_connect_stmt(self) -> ConnectStmt:
        """Parse a connect statement."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_CONNECT)
        
        src = self.parse_endpoint()
        if not isinstance(src, PinRef):
            self.diags.error(
                "E104",
                loc,
                "connect left endpoint must be a pin reference (IDENT.IDENT)",
            )
        
        self.expect(TokenKind.ARROW)
        dst = self.parse_endpoint()
        
        self.expect(TokenKind.SEMICOLON)
        
        return ConnectStmt(src, dst, loc)

    def parse_endpoint(self) -> Endpoint:
        """Parse an endpoint (power ref, pin ref, or net ref)."""
        loc = self.current_token().loc
        
        # Check for power.domain
        if self.match(TokenKind.KW_POWER):
            self.consume()
            self.expect(TokenKind.DOT)
            domain = self.expect(TokenKind.IDENT).text
            return PowerRef(domain, loc)
        
        # Check for instance.pin
        if self.match(TokenKind.IDENT):
            first = self.expect(TokenKind.IDENT).text
            
            if self.match(TokenKind.DOT):
                self.consume()
                second = self.expect(TokenKind.IDENT).text
                return PinRef(first, second, loc)
            else:
                # Must be net ref
                return NetRef(first, loc)
        
        self.diags.error("E100", loc, "Expected endpoint (power.domain, instance.pin, or net_name)")
        return NetRef("", loc)

    def parse_constraint_block(self) -> ConstraintBlock:
        """Parse a constraint block."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_CONSTRAINT)
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        return ConstraintBlock(attrs, loc)

    def parse_placement_block(self) -> PlacementBlock:
        """Parse a placement block."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_PLACEMENT)
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        return PlacementBlock(attrs, loc)

    def parse_routing_block(self) -> RoutingBlock:
        """Parse a routing block."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_ROUTING)
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        return RoutingBlock(attrs, loc)

    def parse_validate_block(self) -> ValidateBlock:
        """Parse a validate block."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_VALIDATE)
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        return ValidateBlock(attrs, loc)

    def parse_simulate_block(self) -> SimulateBlock:
        """Parse a simulate block."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_SIMULATE)
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        return SimulateBlock(attrs, loc)

    def parse_target_decl(self) -> TargetDecl:
        """Parse a target declaration."""
        loc = self.current_token().loc
        self.expect(TokenKind.KW_TARGET)
        
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.LBRACE)
        
        attrs = []
        while not self.match(TokenKind.RBRACE, TokenKind.EOF):
            attrs.append(self.parse_attr_stmt())
        
        self.expect(TokenKind.RBRACE)
        
        return TargetDecl(name, attrs, loc)

    def parse_attr_stmt(self) -> AttrStmt:
        """Parse an attribute statement."""
        loc = self.current_token().loc
        
        key = self.parse_attr_key()
        self.expect(TokenKind.COLON)
        val = self.parse_attr_val()
        self.expect(TokenKind.SEMICOLON)
        
        return AttrStmt(key, val, loc)

    def parse_attr_key(self) -> AttrKey:
        """Parse an attribute key (may be dotted)."""
        loc = self.current_token().loc
        
        parts = [self.expect(TokenKind.IDENT).text]
        
        if self.match(TokenKind.DOT):
            self.consume()
            parts.append(self.expect(TokenKind.IDENT).text)
        
        return AttrKey(parts, loc)

    def parse_attr_val(self) -> AttrVal:
        """Parse an attribute value."""
        loc = self.current_token().loc
        
        if self.match(TokenKind.STRING):
            text = self.expect(TokenKind.STRING).text
            return StringVal(text, loc)
        
        elif self.match(TokenKind.KW_TRUE, TokenKind.KW_FALSE):
            token = self.consume()
            return BoolVal(token.kind == TokenKind.KW_TRUE, loc)
        
        elif self.match(TokenKind.LBRACKET):
            return self.parse_list_val()
        
        elif self.match(TokenKind.NUMBER):
            return self.parse_phys_or_range_val()
        
        elif self.match(TokenKind.IDENT):
            name = self.expect(TokenKind.IDENT).text
            return IdentVal(name, loc)
        
        else:
            self.diags.error("E100", loc, f"Expected attribute value, got {self.current_token().text}")
            return StringVal("", loc)

    def parse_phys_or_range_val(self) -> Union[PhysVal, RangeVal]:
        """Parse a physical value or range."""
        loc = self.current_token().loc
        
        num_text = self.expect(TokenKind.NUMBER).text
        number = float(num_text) if "." in num_text or "e" in num_text.lower() else float(num_text)
        
        unit = ""
        if self.match(TokenKind.UNIT):
            unit = self.expect(TokenKind.UNIT).text
            low = PhysVal(number, unit, loc)
        else:
            # Integer without unit
            return IntVal(int(number), loc)
        
        # Check for range
        if self.match(TokenKind.KW_TO):
            self.consume()
            
            num_text2 = self.expect(TokenKind.NUMBER).text
            number2 = float(num_text2) if "." in num_text2 or "e" in num_text2.lower() else float(num_text2)
            
            unit2 = ""
            if self.match(TokenKind.UNIT):
                unit2 = self.expect(TokenKind.UNIT).text
            
            high = PhysVal(number2, unit2, SourceLoc(loc.file, loc.line, loc.col))
            return RangeVal(low, high, loc)
        
        return low

    def parse_list_val(self) -> ListVal:
        """Parse a list value."""
        loc = self.current_token().loc
        self.expect(TokenKind.LBRACKET)
        
        items = []
        while not self.match(TokenKind.RBRACKET, TokenKind.EOF):
            items.append(self.parse_attr_val())
            
            if self.match(TokenKind.COMMA):
                self.consume()
        
        self.expect(TokenKind.RBRACKET)
        
        return ListVal(items, loc)
