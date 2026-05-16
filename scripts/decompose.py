import os
import sys
import subprocess
from pathlib import Path
import time

def get_working_file(folder_path):
    return folder_path / ".WORKING"

def get_terminal_file(folder_path):
    return folder_path / "TERMINAL_TASK"

def delete_agent(agent_id):
    """ Deletes a scion agent if it exists. """
    agent_dir = Path(".scion/agents") / agent_id
    if not agent_dir.exists():
        return
    print(f"Cleaning up agent: {agent_id}")
    try:
        subprocess.run(["scion", "delete", agent_id], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass
    except FileNotFoundError:
        print("Error: 'scion' command not found.", file=sys.stderr)

def process_folder(folder_path):
    """ Recursively processes folders according to the task decomposition logic. """
    folder = Path(folder_path).resolve()
    working_file = get_working_file(folder)
    terminal_file = get_terminal_file(folder)

    # -- If it has a "TERMINAL_TASK" file, skip the folder, it is done
    if terminal_file.exists():
        if working_file.exists():
            working_file.unlink()
        delete_agent(folder.name)
        return False

    # -- if it has a subtasks folder, recurse and check if any subtasks are still working
    subtasks_folder = folder / "subtasks"
    if subtasks_folder.exists() and subtasks_folder.is_dir():
        if working_file.exists():
            working_file.unlink()
        still_working = False
        for item in subtasks_folder.iterdir():
            if item.is_dir():
                if process_folder(item):
                    still_working = True
        if not still_working:
            delete_agent(folder.name)
        return still_working

    # -- if it has a "WORKING" file and no subtasks or terminal file yet, it is still being worked on
    if working_file.exists():
        return True

    # -- if none of these conditions has been met, then this folder needs to be decomposed
    task_slug = folder.name
    
    try:
        rel_path = folder.relative_to(Path.cwd())
    except ValueError:
        rel_path = folder

    current_branch = os.environ.get("SCION_BRANCH")
    if not current_branch:
        try:
            current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        except subprocess.CalledProcessError:
            current_branch = "main"

    # Auto-commit to bypass the Worktree Trap before spawning agents
    try:
        subprocess.run(["git", "add", "."], cwd=Path.cwd(), stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-c", "user.name=Jihun Kim", "-c", "user.email=jihunkim0@users.noreply.github.com", "commit", "-m", f"Auto-commit {task_slug} task before decomposition"], cwd=Path.cwd(), stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "push", "origin", "HEAD"], cwd=Path.cwd(), stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception as e:
        pass

    prompt = f"git pull origin {current_branch} --no-edit && cd {rel_path} && decompose this task. To mark as terminal, create {terminal_file.absolute()}. DO NOT WORRY ABOUT LOCK FILES."
    command = ["scion", "start", "-t", "tasker", task_slug, prompt, "--non-interactive"]
    
    print(f"Decomposing task: {task_slug} in {folder} (pulling from {current_branch})")
    try:
        working_file.touch()
        # Non-blocking async call unlocks massive swarm parallelization
        subprocess.Popen(command, cwd=Path.cwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("Error: 'scion' command not found.", file=sys.stderr)
    
    return True

def generate_mermaid_graph(root_folder):
    """ Generates a Mermaid.js diagram of the decomposed task tree. """
    root_path = Path(root_folder).resolve()
    graph_lines = ["# Architecture Dependency Graph\n\n```mermaid", "graph TD"]
    
    def walk_tree(folder, parent_id):
        subtasks_dir = folder / "subtasks"
        if subtasks_dir.exists() and subtasks_dir.is_dir():
            for child in sorted(subtasks_dir.iterdir()):
                if child.is_dir():
                    child_id = child.name.replace("-", "_")
                    label = child.name
                    # Read target agent metadata if terminal task
                    if get_terminal_file(child).exists():
                        task_file = child / "task.md"
                        agent = "Unassigned"
                        if task_file.exists():
                            for line in task_file.read_text().splitlines():
                                if line.startswith("Target-Agent:"):
                                    agent = line.split(":", 1)[1].strip()
                                    break
                        label += f"\\n({agent})"
                    
                    graph_lines.append(f"    {parent_id} --> {child_id}[\"{label}\"]")
                    walk_tree(child, child_id)

    root_id = root_path.name.replace("-", "_")
    graph_lines.append(f"    {root_id}[\"{root_path.name}\"]")
    walk_tree(root_path, root_id)
    graph_lines.append("```\n")
    
    graph_file = root_path / "architecture-graph.md"
    graph_file.write_text("\n".join(graph_lines))
    print(f"\nArchitecture graph successfully generated at: {graph_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python decompose.py <folder>")
        sys.exit(1)
    
    target_folder = sys.argv[1]
    if not os.path.isdir(target_folder):
        print(f"Error: {target_folder} is not a directory.")
        sys.exit(1)
        
    still_working = True
    while still_working:
        print("Agents are working... pulling latest git state")
        try:
            subprocess.run(["git", "pull", "origin", "HEAD", "--no-edit"], cwd=Path.cwd(), stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except Exception:
            pass
            
        still_working = process_folder(target_folder)
        if still_working:
            time.sleep(10)
        
    print("\nAll decomposition is done. Generating dependency graph...")
    generate_mermaid_graph(target_folder)