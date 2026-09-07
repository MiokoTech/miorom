from miorom.script import (
    BlockStmt,
    DisassembledScript,
    IfStmt,
    Instruction,
    InstructionStmt,
    ReturnStmt,
    ScriptAST,
    ScriptASTBuilder,
    WhileStmt,
)


def test_ast_if_else_diamond():
    # Construct an If-Else diamond script:
    # 0x0000: INIT
    # 0x0001: IF_FLAG flag=10, target=LABEL_0005
    # 0x0003: GIVE_GOLD amount=100
    # 0x0004: JUMP target=LABEL_0006
    # 0x0005: TAKE_GOLD amount=50 (LABEL_0005)
    # 0x0006: END (LABEL_0006)
    instructions = [
        Instruction(0, 1, "INIT", {}),
        Instruction(1, 2, "IF_FLAG", {"flag": 10, "target": "LABEL_0005"}),
        Instruction(3, 3, "GIVE_GOLD", {"amount": 100}),
        Instruction(4, 4, "JUMP", {"target": "LABEL_0006"}),
        Instruction(5, 5, "TAKE_GOLD", {"amount": 50}, label="LABEL_0005"),
        Instruction(6, 6, "END", {}, label="LABEL_0006"),
    ]
    script = DisassembledScript(instructions=instructions)

    ast = ScriptASTBuilder.from_script(script, function_name="quest_reward")
    py_code = ast.to_python()
    c_code = ast.to_c()

    # Verify python output
    assert "def quest_reward():" in py_code
    assert "INIT()" in py_code
    assert "if IF_FLAG(flag=10):" in py_code
    assert "TAKE_GOLD(amount=50)" in py_code
    assert "else:" in py_code
    assert "GIVE_GOLD(amount=100)" in py_code
    assert "return  # END" in py_code

    # Verify C output
    assert "void quest_reward(void) {" in c_code
    assert "if (IF_FLAG(flag=10)) {" in c_code
    assert "} else {" in c_code
    assert "return;" in c_code


def test_ast_while_loop():
    # Construct a loop with a back-edge:
    # 0x0000: INIT
    # 0x0002: TICK_TIMER step=1 (LABEL_0002)
    # 0x0003: WHILE_NOT_DONE target=LABEL_0002
    # 0x0005: END (LABEL_0005)
    instructions = [
        Instruction(0, 1, "INIT", {}),
        Instruction(2, 2, "TICK_TIMER", {"step": 1}, label="LABEL_0002"),
        Instruction(3, 3, "WHILE_NOT_DONE", {"target": "LABEL_0002"}),
        Instruction(5, 4, "END", {}, label="LABEL_0005"),
    ]
    script = DisassembledScript(instructions=instructions)

    ast = ScriptASTBuilder.from_script(script, function_name="wait_loop")
    py_code = ast.to_python()

    assert "def wait_loop():" in py_code
    assert "while WHILE_NOT_DONE():" in py_code
    assert "TICK_TIMER(step=1)" in py_code
    assert "return  # END" in py_code
