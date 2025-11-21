import json
import re
import sys
import signal
import contextlib
import sys

# --- Timeout Handler ---
class TimeoutException(Exception):
    pass

@contextlib.contextmanager
def time_limit(seconds):
    """
    Sets a timeout for a block of code.
    Note: This uses signal.SIGALRM, which works on Unix/Linux/macOS.
    It does not work on Windows.
    """
    def signal_handler(signum, frame):
        raise TimeoutException("Timed out!")
    
    # Register the signal function handler
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        # Disable the alarm
        signal.alarm(0)

def clean_code(text):
    """
    Extracts and cleans Python code from LLM response.
    Strategies:
    1. Markdown Blocks: Extracts and concatenates all blocks.
    2. Heuristic: Finds start of code (def/import) if no blocks.
    3. Raw: Returns original text as fallback.
    """
    if not text:
        return ""

    # Strategy 1: Find all markdown blocks (```...```)
    # Matches ```python, ```go, or just ```
    pattern_block = r"```(?:[\w\+\-\.]*)?\s+(.*?)```"
    matches = re.findall(pattern_block, text, re.DOTALL)
    
    if matches:
        # Join blocks with newlines to handle imports + function definitions
        return "\n\n".join(matches).strip()

    # Strategy 2: Heuristic search for code start
    # Looks for 'def', 'class', 'import' at the start of a line
    pattern_code_start = r"(?m)^(def |class |import |from )"
    match = re.search(pattern_code_start, text)
    
    if match:
        return text[match.start():].strip()

    # Strategy 3: Return raw text
    return text.strip()

def run_test(code, test_cases, setup_code="", timeout_duration=3):
    """
    Executes the code with a timeout.
    Returns True if passed, False if failed or timed out.
    """
    # Create a dedicated execution scope
    scope = {}
    
    # Pre-load standard libraries common in benchmarks
    header = "import math\nimport re\nimport heapq\nimport sys\nimport collections\nimport itertools\n"
    
    full_code = header + setup_code + "\n" + code
    
    try:
        # Apply the timeout context manager
        with time_limit(timeout_duration):
            # 1. Define the functions/classes
            exec(full_code, scope)
            
            # 2. Run the assertions
            for test in test_cases:
                exec(test, scope)
                
        return True

    except TimeoutException:
        # print("Timeout!") # Uncomment for debugging
        return False
    except Exception as e:
        # print(f"Error: {e}") # Uncomment for debugging
        return False

def compute_pass_at_1(file_path):
    total_tasks = 0
    passed_tasks = 0
    
    print(f"Processing {file_path} with timeout protection...")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line: continue
                
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Handle different JSON structures
                if 'resps' in data and len(data['resps']) > 0:
                    raw_response = data['resps'][0][0]
                elif 'code' in data:
                    raw_response = data['code']
                else:
                    continue

                test_cases = data['doc']['test_list']
                setup_code = data['doc'].get('test_setup_code', "")
                
                # 1. Clean
                sanitized_code = clean_code(raw_response)
                
                # 2. Run (with timeout default of 3 seconds)
                if run_test(sanitized_code, test_cases, setup_code, timeout_duration=3):
                    passed_tasks += 1
                
                total_tasks += 1
                
                if total_tasks % 50 == 0:
                    print(f"Processed {total_tasks} tasks...")

        if total_tasks == 0:
            print("No tasks found.")
            return 0.0
            
        score = passed_tasks / total_tasks
        print("-" * 30)
        print(f"Total Tasks: {total_tasks}")
        print(f"Passed:      {passed_tasks}")
        print(f"Pass@1:      {score:.4f}")
        print("-" * 30)
        return score

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")

if __name__ == "__main__":
    # Replace with your filename
    compute_pass_at_1(sys.argv[1])
