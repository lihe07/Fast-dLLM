import json
import re
import sys
import signal
import contextlib
import ast
import traceback


# --- 1. Timeout Context ---
class TimeoutException(Exception):
    pass


@contextlib.contextmanager
def time_limit(seconds):
    if hasattr(signal, "SIGALRM"):

        def signal_handler(signum, frame):
            raise TimeoutException("Timed out!")

        signal.signal(signal.SIGALRM, signal_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
    else:
        yield


# --- 2. Text Extraction & Normalization ---
def extract_code(text):
    if not text:
        return ""
    # Fix non-breaking spaces
    text = text.replace("\u00a0", " ")

    # Markdown Blocks (Concatenate all blocks)
    pattern_block = r"```(?:[\w\+\-\.]*)?\s+(.*?)```"
    matches = re.findall(pattern_block, text, re.DOTALL)
    if matches:
        return "\n\n".join(matches)

    # Heuristic Start
    match = re.search(r"(?m)^(def |class |import |from )", text)
    if match:
        return text[match.start() :]

    return text


# --- 3. Advanced AST Processing ---
def get_function_names(tree):
    """Returns a list of function names defined in the AST."""
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


def get_required_function_name(test_cases):
    """Finds the function name the tests are trying to call."""
    code = "\n".join(test_cases)
    # Regex to find 'assert function_name('
    match = re.search(r"(?:assert\s+)?(\w+)\(", code)
    if match:
        return match.group(1)
    return None


def process_and_sanitize(source_code):
    """
    1. Prunes syntax errors (trailing text).
    2. Removes self-testing Asserts/Prints.
    3. Returns compiled object + list of defined functions.
    """
    lines = source_code.splitlines()
    tree = None

    # A. Iterative Syntax Pruning
    for _ in range(10):
        try:
            current_source = "\n".join(lines)
            tree = ast.parse(current_source)
            break
        except SyntaxError as e:
            if "unexpected EOF" in str(e.msg):
                return None, []
            # Cut off at error line
            lines = lines[: e.lineno - 1]
            if not lines:
                return None, []
    else:
        return None, []

    # B. AST Sanitization (Remove LLM's self-tests)
    new_body = []
    for node in tree.body:
        # Remove global asserts
        if isinstance(node, ast.Assert):
            continue
        # Remove global print() calls
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if hasattr(node.value.func, "id") and node.value.func.id == "print":
                continue
        new_body.append(node)
    tree.body = new_body

    try:
        ast.fix_missing_locations(tree)
        # Extract defined function names for aliasing later
        defined_funcs = get_function_names(tree)
        return compile(tree, filename="<ast>", mode="exec"), defined_funcs
    except Exception:
        return None, []


# --- 4. Execution Engine with Aliasing ---
def run_test(raw_code, test_cases, setup_code="", timeout_duration=3):
    scope = {}
    # Standard Library Imports
    header = "import math\nimport re\nimport heapq\nimport sys\nimport collections\nimport itertools\n"

    # 1. Extract & Prepare
    text = extract_code(raw_code)
    full_source = header + setup_code + "\n" + text

    # 2. Sanitize
    compiled_obj, defined_funcs = process_and_sanitize(full_source)

    if compiled_obj is None:
        return False  # Still SyntaxError after pruning

    try:
        with time_limit(timeout_duration):
            # 3. Execute Definitions
            exec(compiled_obj, scope)

            # 4. SMART ALIASING (The Fix for TestRuntimeError)
            required_func = get_required_function_name(test_cases)

            if required_func and required_func not in scope:
                # If the test wants 'remove_Occ' but we only have 'solve', mapping them.
                # We ignore standard imported names and look for user-defined ones.
                candidates = [f for f in defined_funcs if f in scope]
                if candidates:
                    # Heuristic: The last defined function is usually the solution
                    best_guess = candidates[-1]
                    scope[required_func] = scope[best_guess]

            # 5. Run Tests
            for test in test_cases:
                exec(test, scope)

        return True
    except Exception:
        return False


# --- 5. Main Loop ---
def compute_final_score(file_path):
    total = 0
    passed = 0

    print(f"Processing {file_path} with Final Gold Standard Evaluator...")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except:
                    continue

                if "resps" in data and data["resps"]:
                    raw = data["resps"][0][0]
                elif "code" in data:
                    raw = data["code"]
                else:
                    continue

                # Execute
                if run_test(
                    raw,
                    data["doc"]["test_list"],
                    data["doc"].get("test_setup_code", ""),
                ):
                    passed += 1

                total += 1
                if total % 100 == 0:
                    print(f"Processed {total}...")

        if total == 0:
            return 0.0

        score = passed / total
        print("=" * 30)
        print(f"Total Tasks: {total}")
        print(f"Passed:      {passed}")
        print(f"Score:       {score:.4f}")
        print("=" * 30)
        return score

    except FileNotFoundError:
        print("File not found.")


if __name__ == "__main__":
    compute_final_score(sys.argv[1])
