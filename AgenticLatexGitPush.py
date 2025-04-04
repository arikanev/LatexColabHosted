import os
import time
import subprocess
import argparse
import getpass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging
import urllib.parse
import threading
import git
import fcntl
from pathlib import Path

from Client_example import send_box, send_log, shutdown_server

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Add this near the top of your script
system_type = "unknown"
try:
    if os.path.exists("/etc/debian_version"):
        system_type = "debian"
    elif os.path.exists("/etc/fedora-release") or os.path.exists("/etc/redhat-release"):
        system_type = "fedora"
except Exception:
    pass


def map_package_to_debian(package_name):
    """
    Maps LaTeX package names to Debian/Ubuntu package names
    Returns a list of possible Debian package names for the given LaTeX package
    """
    # Common mappings for frequently used LaTeX packages to Debian/Ubuntu packages
    debian_mappings = {
        # Core packages
        "xcolor": ["texlive-latex-recommended"],
        "amsmath": ["texlive-latex-base"],
        "amssymb": ["texlive-latex-recommended"],
        "amsthm": ["texlive-latex-recommended"],
        "geometry": ["texlive-latex-recommended"],
        "graphicx": ["texlive-latex-recommended"],
        "hyperref": ["texlive-latex-recommended"],
        
        # Extended packages
        "tcolorbox": ["texlive-latex-extra"],
        "framed": ["texlive-latex-extra"],
        "etoolbox": ["texlive-latex-extra"],
        "fancyhdr": ["texlive-latex-extra"],
        "tikz": ["texlive-pictures"],
        "pgf": ["texlive-pictures"],
        "pstricks": ["texlive-pstricks"],
        "biblatex": ["texlive-bibtex-extra"],
        "beamer": ["texlive-latex-recommended"],
        
        # Font packages
        "fontspec": ["texlive-fonts-extra"],
        "lmodern": ["texlive-fonts-recommended"],
        
        # Math and science
        "mathtools": ["texlive-science"],
        "siunitx": ["texlive-science"],
        "physics": ["texlive-science"],
        "chemfig": ["texlive-science"],
        
        # Language and encoding
        "babel": ["texlive-lang-all"],
        "inputenc": ["texlive-latex-base"],
        "fontenc": ["texlive-latex-base"],
    }
    
    # Check if we have a direct mapping
    if package_name in debian_mappings:
        return debian_mappings[package_name]
    
    # For packages not in our mapping, suggest likely collections
    # Most packages are in texlive-latex-extra
    return ["texlive-latex-extra", "texlive-latex-recommended"]

def try_debian_package_installation(packages):
    """
    Attempt to install LaTeX packages using Debian/Ubuntu package manager
    Uses multiple approaches including package mapping and metapackages
    """
    logger.info("Attempting to install LaTeX packages using apt-get...")
    
    # Step 1: Try mapping each package to Debian packages
    all_debian_packages = set()
    for pkg in packages:
        debian_pkgs = map_package_to_debian(pkg)
        all_debian_packages.update(debian_pkgs)
    
    # Remove duplicates and convert to list
    debian_packages_list = list(all_debian_packages)
    logger.info(f"Mapped LaTeX packages to Debian packages: {', '.join(debian_packages_list)}")
    
    # Step 2: Try installing the mapped packages
    try:
        cmd = ["sudo", "apt-get", "install", "-y"] + debian_packages_list
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        
        if result.returncode == 0:
            logger.info("Successfully installed LaTeX packages using apt-get")
            return True
        else:
            logger.warning(f"Failed to install mapped packages: {result.stderr}")
    except Exception as e:
        logger.warning(f"Error installing mapped packages: {str(e)}")
    
    # Step 3: Try common metapackages that cover most LaTeX needs
    metapackages = [
        "texlive-latex-recommended",
        "texlive-latex-extra",
        "texlive-fonts-recommended",
        "texlive-science"
    ]
    
    try:
        cmd = ["sudo", "apt-get", "install", "-y"] + metapackages
        logger.info(f"Trying metapackages: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        
        if result.returncode == 0:
            logger.info("Successfully installed LaTeX metapackages")
            return True
        else:
            logger.warning(f"Failed to install metapackages: {result.stderr}")
    except Exception as e:
        logger.warning(f"Error installing metapackages: {str(e)}")
    
    # Step 4: Last resort - try texlive-full
    try:
        logger.info("Trying texlive-full as a last resort (large but comprehensive)...")
        cmd = ["sudo", "apt-get", "install", "-y", "texlive-full"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
        
        if result.returncode == 0:
            logger.info("Successfully installed texlive-full")
            return True
        else:
            logger.warning(f"Failed to install texlive-full: {result.stderr}")
    except Exception as e:
        logger.warning(f"Error installing texlive-full: {str(e)}")
    
    return False


def extract_latex_errors(log_output):
    """
    Extract more detailed error information from LaTeX output
    Returns a list of error messages
    """
    errors = []
    lines = log_output.split('\n')
    
    # Flag to track if we're in an error section
    in_error = False
    current_error = ""
    
    for i, line in enumerate(lines):
        # Check for common error markers
        if line.startswith('!') or ('! ' in line and not line.startswith(' ')):
            if in_error and current_error:  # Save previous error if it exists
                errors.append(current_error.strip())
            
            in_error = True
            current_error = line
        elif in_error:
            # Continue collecting lines that are part of the current error
            # Usually errors span multiple lines with context
            if line.strip() and not line.startswith('l.'):  # Skip line number references
                current_error += "\n" + line
            
            # Check for end of error section
            if 'erro' not in line.lower() and 'warn' not in line.lower() and line.strip() == '':
                in_error = False
                if current_error:
                    errors.append(current_error.strip())
                current_error = ""
    
    # Add the last error if we were still in an error section
    if in_error and current_error:
        errors.append(current_error.strip())
    
    # Look for specific patterns in the log if no errors were found
    if not errors:
        for line in lines:
            for error_pattern in [
                "Emergency stop", 
                "Fatal error", 
                "No pages of output",
                "Undefined control sequence",
                "Missing "
            ]:
                if error_pattern in line:
                    # Get a few lines of context
                    context_index = lines.index(line)
                    context_start = max(0, context_index - 3)
                    context_end = min(len(lines), context_index + 4)
                    context = "\n".join(lines[context_start:context_end])
                    errors.append(context)
                    break
    
    # Add compilation info from log if we still have no errors
    if not errors:
        # Look for any warnings or issues
        for line in lines:
            if any(pattern in line for pattern in [
                "warning", "undefined", "missing", "error"
            ]):
                errors.append(line.strip())
    
    return errors

def check_package_paths():
    """
    Check if LaTeX can find the installed packages
    Returns a tuple of (status, paths)
    """
    try:
        # Run kpsewhich to check LaTeX paths
        result = subprocess.run(
            ["kpsewhich", "-var-value=TEXMFHOME"], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        texmf_home = result.stdout.strip()
        
        # Get system paths
        result = subprocess.run(
            ["kpsewhich", "-var-value=TEXMFDIST"], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        texmf_dist = result.stdout.strip()
        
        # Check for specific packages to confirm they're findable
        test_packages = ["xcolor.sty", "amsmath.sty", "geometry.sty"]
        package_paths = {}
        
        for pkg in test_packages:
            result = subprocess.run(
                ["kpsewhich", pkg], 
                capture_output=True, 
                text=True, 
                check=False
            )
            
            if result.stdout.strip():
                package_paths[pkg] = result.stdout.strip()
            else:
                package_paths[pkg] = "Not found"
        
        # Check if TeX Live is using correct TEXMFVAR
        result = subprocess.run(
            ["kpsewhich", "-var-value=TEXMFVAR"], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        texmf_var = result.stdout.strip()
        
        # Get TeX format information
        result = subprocess.run(
            ["pdflatex", "--version"], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        tex_version = result.stdout.strip()
        
        paths_info = {
            "TEXMFHOME": texmf_home,
            "TEXMFDIST": texmf_dist,
            "TEXMFVAR": texmf_var,
            "TeX Version": tex_version,
            "Package Paths": package_paths
        }
        
        # Check if paths exist
        for path_name, path in [("TEXMFHOME", texmf_home), ("TEXMFDIST", texmf_dist), ("TEXMFVAR", texmf_var)]:
            if path and os.path.exists(path):
                paths_info[f"{path_name} exists"] = "Yes"
            else:
                paths_info[f"{path_name} exists"] = "No"
        
        # Determine status
        if all(v != "Not found" for v in package_paths.values()):
            return (True, paths_info)
        else:
            return (False, paths_info)
            
    except Exception as e:
        return (False, {"error": str(e)})

def fix_texlive_paths():
    """
    Attempt to fix TeX Live path issues
    Returns True if successful
    """
    try:
        # Check current user's home directory
        home_dir = os.path.expanduser("~")
        
        # Check if texmf directory exists in home
        texmf_home = os.path.join(home_dir, "texmf")
        if not os.path.exists(texmf_home):
            os.makedirs(texmf_home, exist_ok=True)
            logger.info(f"Created TEXMFHOME directory at {texmf_home}")
        
        # Check for texture directory
        texture_dir = os.path.join(texmf_home, "tex", "latex")
        if not os.path.exists(texture_dir):
            os.makedirs(texture_dir, exist_ok=True)
            logger.info(f"Created LaTeX directory at {texture_dir}")
        
        # Create a simple test package file to verify paths work
        test_file = os.path.join(texture_dir, "texlive-test.sty")
        with open(test_file, 'w') as f:
            f.write("\\ProvidesPackage{texlive-test}[2025/02/26 Test Package]\\endinput")
        
        # Refresh TeX file database
        try:
            subprocess.run(["mktexlsr"], check=False, capture_output=True)
            logger.info("Refreshed TeX file database with mktexlsr")
        except:
            logger.info("Could not refresh TeX file database")
        
        # Test if package is found
        result = subprocess.run(
            ["kpsewhich", "texlive-test.sty"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.stdout.strip():
            logger.info(f"Successfully verified TeX paths: {result.stdout.strip()}")
            return True
        else:
            logger.warning("Could not verify TeX paths after fix attempts")
            return False
    
    except Exception as e:
        logger.error(f"Error fixing TeX Live paths: {str(e)}")
        return False

def verify_package_installation(packages):
    """
    Verify that packages are actually installed and accessible to LaTeX
    Returns a tuple (all_found, dict_of_results)
    """
    results = {}
    all_found = True
    
    try:
        for pkg in packages:
            pkg_file = f"{pkg}.sty"
            
            # Use kpsewhich to check if LaTeX can find the package
            result = subprocess.run(
                ["kpsewhich", pkg_file],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.stdout.strip():
                # Package found
                results[pkg] = {
                    "found": True,
                    "path": result.stdout.strip()
                }
            else:
                # Package not found
                all_found = False
                results[pkg] = {
                    "found": False,
                    "path": None
                }
                
                # Try to find package in system directories
                for texmf_dir in ["/usr/share/texlive/texmf-dist", "/usr/share/texmf", "/usr/local/texlive"]:
                    if os.path.exists(texmf_dir):
                        # Use find to locate the package
                        find_cmd = ["find", texmf_dir, "-name", pkg_file]
                        find_result = subprocess.run(
                            find_cmd,
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if find_result.stdout.strip():
                            results[pkg]["system_path"] = find_result.stdout.strip()
                            break
        
        return (all_found, results)
    
    except Exception as e:
        logger.error(f"Error verifying package installation: {str(e)}")
        return (False, {"error": str(e)})

# Helper functions moved outside of class for better access
# def extract_latex_errors(log_output):
#     """Extract relevant error messages from LaTeX log output"""
#     errors = []
#     lines = log_output.split('\n')
    
#     for i, line in enumerate(lines):
#         if "! " in line:  # LaTeX error indicator
#             error_msg = line.strip()
#             # Add some context lines
#             if i+1 < len(lines) and lines[i+1].strip():
#                 error_msg += " - " + lines[i+1].strip()
#             errors.append(error_msg)
    
#     # If no specific errors found but compilation failed, return general message
#     if not errors and "Fatal error occurred" in log_output:
#         errors.append("Fatal error occurred during compilation. Check full log file.")
        
#     return errors


def extract_missing_packages(log_output):
    """
    Extract missing package names from LaTeX log output
    Enhanced to detect packages with different error patterns
    """
    missing_packages = []
    lines = log_output.split('\n')
    
    for i, line in enumerate(lines):
        # Pattern 1: The standard error message for missing packages
        if "! LaTeX Error: File" in line and "not found" in line:
            # Extract the package name (usually in the format 'package.sty')
            parts = line.split("'")
            if len(parts) >= 2:
                package_file = parts[1]
                # Remove file extension (.sty) to get package name
                if package_file.endswith('.sty'):
                    package_name = package_file[:-4]  # Remove '.sty'
                    missing_packages.append(package_name)
        
        # Pattern 2: Another common error format
        elif "! LaTeX Error: File `" in line and ".sty' not found" in line:
            # Extract between backtick and .sty
            try:
                package_file = line.split('`')[1].split("'")[0]
                if package_file.endswith('.sty'):
                    package_name = package_file[:-4]
                    missing_packages.append(package_name)
            except (IndexError, KeyError):
                continue
        
        # Pattern 3: MikTeX specific errors
        elif "! Package " in line and "Error: File" in line and "not found" in line:
            try:
                # Try to get the next line for more info
                next_line = lines[i+1] if i+1 < len(lines) else ""
                if '.sty' in next_line:
                    # Look for .sty file in the next line
                    for word in next_line.split():
                        if word.endswith('.sty'):
                            package_name = word[:-4]
                            missing_packages.append(package_name)
            except (IndexError, KeyError):
                continue
        
        # Pattern 4: Simple pattern matching for any line containing both .sty and not found
        elif ".sty" in line and "not found" in line:
            for word in line.split():
                if word.endswith('.sty') or word.endswith('.sty.'):
                    # Clean up the word to get just the package name
                    package_name = word.rstrip('.,').strip()[:-4]
                    if package_name and package_name not in missing_packages:
                        missing_packages.append(package_name)
    
    # Remove duplicates and return
    return list(set(missing_packages))

def extract_packages_from_source(content):
    """
    Extract package names from LaTeX source
    Enhanced to detect more package inclusion patterns
    """
    packages = []
    
    # Look for various package commands
    import re
    
    # Pattern 1: Standard \usepackage commands
    # Match both \usepackage{pkg} and \usepackage[options]{pkg}
    pattern1 = r'\\usepackage(?:\[.*?\])?\{([^}]+)\}'
    matches1 = re.findall(pattern1, content)
    
    # Pattern 2: RequirePackage commands 
    # Often used in class and style files
    pattern2 = r'\\RequirePackage(?:\[.*?\])?\{([^}]+)\}'
    matches2 = re.findall(pattern2, content)
    
    # Combine all matches
    all_matches = matches1 + matches2
    
    for match in all_matches:
        # Some package commands include multiple packages separated by commas
        pkgs = [pkg.strip() for pkg in match.split(',')]
        packages.extend(pkgs)
    
    # Add some common dependencies that might not be explicitly mentioned
    # For example, if tikz is used, pgf is needed
    if 'tikz' in packages and 'pgf' not in packages:
        packages.append('pgf')
    if 'hyperref' in packages and 'url' not in packages:
        packages.append('url')
    if 'color' in packages and 'xcolor' not in packages:
        packages.append('xcolor')  # xcolor is often a better alternative to color
    if 'tcolorbox' in packages and 'xcolor' not in packages:
        packages.append('xcolor')  # tcolorbox requires xcolor
        
    # Document class detection - some document classes need specific packages
    class_pattern = r'\\documentclass(?:\[.*?\])?\{([^}]+)\}'
    class_matches = re.findall(class_pattern, content)
    if class_matches:
        doc_class = class_matches[0].strip()
        if doc_class == 'beamer' and 'xcolor' not in packages:
            packages.append('xcolor')  # beamer needs xcolor
    
    # Remove duplicates and return
    return list(set(packages))

def install_latex_packages(packages):
    """
    Attempt to install missing LaTeX packages using the appropriate package manager
    Returns True if installation was successful, False otherwise
    """
    if not packages:
        return False
    
    logger.info(f"Attempting to install LaTeX packages: {', '.join(packages)}")
    
    # Detect the LaTeX distribution
    latex_system = detect_latex_system()
    
    if latex_system == "texlive":
        return install_texlive_packages(packages)
    elif latex_system == "miktex":
        return install_miktex_packages(packages)
    else:
        logger.warning(f"Unsupported LaTeX distribution or couldn't detect the distribution.")
        logger.info(f"Please install these packages manually: {', '.join(packages)}")
        return False

def detect_latex_system():
    """Detect which LaTeX distribution is installed"""
    try:
        # Check for TeX Live
        result = subprocess.run(["tlmgr", "--version"], 
                              capture_output=True, 
                              text=True, 
                              check=False)
        if result.returncode == 0:
            return "texlive"
        
        # Check for MiKTeX
        result = subprocess.run(["mpm", "--version"], 
                              capture_output=True, 
                              text=True, 
                              check=False)
        if result.returncode == 0:
            return "miktex"
            
    except FileNotFoundError:
        pass
    
    # If we reach here, couldn't determine the system
    return "unknown"

def install_texlive_packages(packages):
    """Install packages using TeX Live's tlmgr or system package manager"""
    try:
        # Detect the system type
        system_type = "unknown"
        try:
            if os.path.exists("/etc/debian_version"):
                system_type = "debian"
                logger.info("Detected Debian/Ubuntu system")
            elif os.path.exists("/etc/fedora-release") or os.path.exists("/etc/redhat-release"):
                system_type = "fedora"
                logger.info("Detected Fedora/RHEL system")
        except Exception:
            pass
        
        # Check TeX Live version and repository status
        texlive_outdated = False
        try:
            version_check = subprocess.run(
                ["tlmgr", "repository", "list"], 
                capture_output=True, 
                text=True, 
                check=False
            )
            if "older than remote" in version_check.stderr:
                logger.warning("TeX Live installation is outdated compared to repository")
                texlive_outdated = True
        except Exception as e:
            logger.warning(f"Could not check TeX Live version: {str(e)}")
        
        # If TeX Live is outdated, prioritize system package manager
        if texlive_outdated:
            logger.info("Will prioritize system package manager due to outdated TeX Live")
        
        # Create a mapping of package installation methods for different scenarios
        installation_methods = []
        
        # For Debian/Ubuntu systems
        if system_type == "debian":
            # Ubuntu/Debian package naming variations - these are the common patterns
            debian_package_prefixes = [
                "texlive-latex-recommended",  # Common packages
                "texlive-latex-extra",        # Extra packages
                "texlive-fonts-recommended",  # Font packages
                "texlive-science",            # Scientific packages
                "texlive-plain-generic"       # Generic TeX packages
            ]
            
            for prefix in debian_package_prefixes:
                installation_methods.append({
                    "description": f"apt-get with {prefix}",
                    "command_creator": lambda _: ["sudo", "apt-get", "install", "-y"] + 
                                               [prefix],
                    "requires_admin": True,
                    "bulk_install": True  # Install all packages at once
                })
            
            # Try installing texlive-full as a last resort (large but comprehensive)
            installation_methods.append({
                "description": "apt-get texlive-full (complete TeX Live)",
                "command_creator": lambda _: ["sudo", "apt-get", "install", "-y", "texlive-full"],
                "requires_admin": True,
                "bulk_install": True
            })
        
        # For Fedora/RHEL systems
        elif system_type == "fedora":
            installation_methods.append({
                "description": "dnf with texlive-scheme-medium",
                "command_creator": lambda _: ["sudo", "dnf", "install", "-y", "texlive-scheme-medium"],
                "requires_admin": True,
                "bulk_install": True
            })
            
            installation_methods.append({
                "description": "dnf with texlive-collection-latexextra",
                "command_creator": lambda _: ["sudo", "dnf", "install", "-y", "texlive-collection-latexextra"],
                "requires_admin": True,
                "bulk_install": True
            })
        
        # Add TeX Live methods (if not outdated, or as fallback)
        if not texlive_outdated:
            # Standard tlmgr install
            installation_methods.append({
                "description": "Standard tlmgr install",
                "command_creator": lambda pkg: ["tlmgr", "install", pkg]
            })
            
            # User mode
            installation_methods.append({
                "description": "User mode",
                "command_creator": lambda pkg: ["tlmgr", "--usermode", "install", pkg]
            })
            
            # Sudo
            installation_methods.append({
                "description": "Sudo with tlmgr",
                "command_creator": lambda pkg: ["sudo", "tlmgr", "install", pkg],
                "requires_admin": True
            })
        else:
            # If outdated, suggest updating TeX Live
            logger.info("Attempting TeX Live update for outdated installation...")
            try:
                update_cmd = ["tlmgr", "update", "--self", "--all"]
                update_result = subprocess.run(update_cmd, capture_output=True, text=True, check=False)
                if update_result.returncode == 0:
                    logger.info("Successfully updated TeX Live")
                    
                    # Now add TeX Live methods since we've updated
                    installation_methods.append({
                        "description": "Standard tlmgr install (after update)",
                        "command_creator": lambda pkg: ["tlmgr", "install", pkg]
                    })
                    
                    installation_methods.append({
                        "description": "User mode (after update)",
                        "command_creator": lambda pkg: ["tlmgr", "--usermode", "install", pkg]
                    })
                else:
                    logger.warning(f"TeX Live update failed: {update_result.stderr}")
            except Exception as e:
                logger.warning(f"Error updating TeX Live: {str(e)}")
        
        # First, try to initialize user mode if needed (only if we'll be using TeX Live methods)
        if not texlive_outdated:
            try:
                logger.info("Attempting to initialize tlmgr user mode...")
                init_cmd = ["tlmgr", "init-usertree"]
                init_result = subprocess.run(init_cmd, capture_output=True, text=True, check=False)
                if init_result.returncode == 0:
                    logger.info("Successfully initialized tlmgr user mode")
                else:
                    # This could be normal - user mode might already be initialized
                    logger.info(f"Note about user mode: {init_result.stderr.strip()}")
            except Exception as e:
                logger.warning(f"Error initializing user mode: {str(e)}")
        
        # Try each installation method until one works
        for method in installation_methods:
            # Skip methods requiring admin if we're not running as admin
            if method.get("requires_admin", False):
                is_admin = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
                if not is_admin:
                    try:
                        # Check if sudo is available without password prompt
                        subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        logger.warning(f"Skipping {method['description']} method (requires admin privileges)")
                        continue
            
            logger.info(f"Trying to install packages using {method['description']} method...")
            
            # Bulk install methods (install all packages at once)
            if method.get("bulk_install", False):
                try:
                    cmd = method["command_creator"](None)  # Doesn't need a package name
                    logger.info(f"Running: {' '.join(cmd)}")
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
                    
                    if result.returncode == 0:
                        logger.info(f"Successfully installed LaTeX packages using {method['description']}")
                        return True
                    else:
                        logger.warning(f"Failed to install using {method['description']}: {result.stderr}")
                except Exception as e:
                    logger.warning(f"Error with {method['description']}: {str(e)}")
                    continue
            
            # Individual package installation
            else:
                success = True
                for pkg in packages:
                    try:
                        cmd = method["command_creator"](pkg)
                        logger.info(f"Running: {' '.join(cmd)}")
                        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
                        
                        if result.returncode == 0:
                            logger.info(f"Successfully installed {pkg} using {method['description']}")
                        else:
                            logger.warning(f"Failed to install {pkg} using {method['description']}: {result.stderr}")
                            success = False
                            break
                    except Exception as e:
                        logger.warning(f"Error installing {pkg} using {method['description']}: {str(e)}")
                        success = False
                        break
                
                if success:
                    logger.info(f"All packages installed successfully using {method['description']}")
                    return True
        
        # If we get here, all methods failed
        logger.error("All installation methods failed. Manual installation is required.")
        
        # Provide helpful information about package installation
        if system_type == "debian":
            logger.info("\nRecommended manual installation for Ubuntu/Debian:")
            logger.info("Run: sudo apt-get install texlive-latex-recommended texlive-latex-extra")
        elif system_type == "fedora":
            logger.info("\nRecommended manual installation for Fedora/RHEL:")
            logger.info("Run: sudo dnf install texlive-scheme-medium")
        else:
            logger.info("\nRecommended manual installation:")
            logger.info("1. Install TeX Live from https://tug.org/texlive/")
            logger.info("2. Then run: tlmgr install " + " ".join(packages))
        
        return False
    except Exception as e:
        logger.error(f"Error installing LaTeX packages: {str(e)}")
        return False

def install_miktex_packages(packages):
    """Install packages using MiKTeX's package manager"""
    try:
        for pkg in packages:
            logger.info(f"Installing MiKTeX package: {pkg}")
            
            # MiKTeX's package manager command
            cmd = ["mpm", "--install", pkg]
            
            # Run the installation command
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                logger.warning(f"Failed to install {pkg}: {result.stderr}")
                # Try with admin mode
                logger.info(f"Retrying with admin privileges...")
                admin_cmd = ["mpm", "--admin", "--install", pkg]
                try:
                    admin_result = subprocess.run(admin_cmd, capture_output=True, text=True, check=False)
                    if admin_result.returncode != 0:
                        logger.warning(f"Failed to install with admin privileges: {admin_result.stderr}")
                        return False
                except Exception:
                    logger.warning("Failed to run with admin privileges. Please install manually.")
                    return False
        
        return True
    except Exception as e:
        logger.error(f"Error installing MiKTeX packages: {str(e)}")
        return False

def open_pdf(pdf_path):
    """Open the PDF file with the default PDF viewer"""
    try:
        import platform
        system = platform.system()
        
        logger.info(f"Opening PDF with system viewer...")
        
        if system == 'Darwin':  # macOS
            subprocess.run(['open', pdf_path], check=False)
        elif system == 'Windows':
            os.startfile(pdf_path)  # Windows-specific
        else:  # Linux and other Unix-like
            subprocess.run(['xdg-open', pdf_path], check=False)
            
    except Exception as e:
        logger.error(f"Error opening PDF: {str(e)}")


def validate_pdf_creation(pdf_path, log_output, return_code):
    """
    Properly validate if a PDF was created successfully based on multiple criteria
    
    Args:
        pdf_path: Path to the expected PDF file
        log_output: Output from the pdflatex command
        return_code: Return code from the pdflatex command
    
    Returns:
        tuple: (pdf_exists, pdf_valid, error_message)
    """
    # Step 1: Check if the file exists
    pdf_exists = os.path.exists(pdf_path)
    
    # Step 2: Check the return code from pdflatex
    compile_success = return_code == 0
    
    # Step 3: Look for fatal error messages in the log
    fatal_error = False
    fatal_error_message = None
    
    error_patterns = [
        "Fatal error occurred",
        "Emergency stop",
        "==> Fatal error occurred",
        "no output PDF file produced"
    ]
    
    for line in log_output.split('\n'):
        for pattern in error_patterns:
            if pattern in line:
                fatal_error = True
                fatal_error_message = line.strip()
                break
        if fatal_error:
            break
    
    # Step 4: If file exists, check if it's a valid PDF by examining the size and header
    pdf_valid = False
    
    if pdf_exists:
        try:
            # Check file size - very small PDFs might be empty or corrupt
            size_bytes = os.path.getsize(pdf_path)
            
            # Check for PDF header - valid PDFs start with %PDF-
            with open(pdf_path, 'rb') as f:
                header = f.read(5)
                has_pdf_header = header == b'%PDF-'
            
            # Minimum size threshold (adjust as needed)
            min_size = 1000  # 1 KB is very small for a real PDF
            
            pdf_valid = size_bytes > min_size and has_pdf_header
            
            if pdf_valid:
                # Valid PDF that exists and has proper structure
                return True, True, None
            elif size_bytes <= min_size:
                return True, False, f"PDF file exists but is too small ({size_bytes} bytes)"
            elif not has_pdf_header:
                return True, False, "File exists but is not a valid PDF (missing PDF header)"
        except Exception as e:
            return pdf_exists, False, f"Error validating PDF: {str(e)}"
    
    # PDF doesn't exist or compilation had fatal errors
    error_msg = fatal_error_message if fatal_error else f"LaTeX compilation failed (return code {return_code})"
    return pdf_exists, False, error_msg


class LatexFileHandler(FileSystemEventHandler):
    def __init__(self, file_path, git_repo_path):
        self.file_path = os.path.abspath(file_path)
        self.git_repo_path = os.path.abspath(git_repo_path)
        self.last_modified = time.time()
        self.cooldown = 5  # Cooldown period in seconds to avoid multiple triggers

    def on_modified(self, event):
        if os.environ.get('GIT_PUSH_DISABLED', False) == 'True':
            return
        
        if event.src_path == self.file_path:
            current_time = time.time()
            # Check if cooldown period has passed
            if current_time - self.last_modified > self.cooldown or \
                os.environ.get('LATEX_COLAB_AGENT_STREAMING', False) == 'True':

                self.last_modified = current_time
                logger.info(f"Change detected in {self.file_path}")
                self.sync_with_overleaf()

    def sync_with_overleaf(self):
        try:
            original_dir = os.getcwd()
            compile_success = True
            
            # Copy the modified file to the git repository
            file_name = os.path.basename(self.file_path)
            dest_path = os.path.join(self.git_repo_path, file_name)
            
            with open(self.file_path, 'r', encoding='utf-8') as source_file:
                content = source_file.read()

            if not content:
                return
                
            with open(dest_path, 'w', encoding='utf-8') as dest_file:
                dest_file.write(content)
            
            # Compile locally if requested
            if hasattr(self, 'local_compilation') and self.local_compilation:
                try:
                    self.compile_locally()
                except Exception as e:
                    logger.error(f"Local compilation failed but continuing with git sync: {str(e)}")
                    compile_success = False
            
            # Git operations - move to git repo directory first
            os.chdir(self.git_repo_path)
            
            # Add and commit the file
            try:
                subprocess.run(["git", "add", file_name], check=True)
                subprocess.run(["git", "commit", "-m", f"Auto-update: {file_name}"], check=True)
                
                # Push to Overleaf
                logger.info("Pushing changes to Overleaf...")
                result = subprocess.run(["git", "push", "origin", "master"], 
                                       check=True, 
                                       capture_output=True, 
                                       text=True)
                
                logger.info("Successfully pushed changes to Overleaf!")
            except subprocess.CalledProcessError as e:
                logger.error(f"Git operation failed: {e.stderr if hasattr(e, 'stderr') else str(e)}")
            finally:
                # Return to original directory
                os.chdir(original_dir)
            
            # Trigger compilation via API if API credentials provided and local compilation not requested
            #if hasattr(self, 'overleaf_api') and self.overleaf_api and not (hasattr(self, 'local_compilation') and self.local_compilation):
            #    self.trigger_compilation()
            
        except Exception as e:
            logger.error(f"Error syncing with Overleaf: {str(e)}")
            # Make sure we're back in the original directory
            try:
                os.chdir(original_dir)
            except:
                pass

    def compile_locally(self):
        """Compile the LaTeX document locally using pdflatex, continue despite errors"""
        try:
            file_name = os.path.basename(self.file_path)
            output_dir = os.path.dirname(self.file_path)
            
            # Change to the directory containing the LaTeX file
            current_dir = os.getcwd()
            os.chdir(os.path.dirname(self.file_path))
            
            # Get the base filename for the PDF
            base_name = os.path.splitext(file_name)[0]
            pdf_path = f"{base_name}.pdf"
            
            # Read the LaTeX file to extract required packages
            # Add error handling for UTF-8 decoding issues
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Try with a more forgiving encoding
                logger.warning("UTF-8 decode error, trying with latin-1 encoding")
                with open(self.file_path, 'r', encoding='latin-1', errors='replace') as f:
                    content = f.read()
            
            # Extract required packages
            required_packages = extract_packages_from_source(content)
            if required_packages:
                logger.info(f"Document requires these packages: {', '.join(required_packages)}")
                
                # Auto-install packages if enabled
                auto_install = (hasattr(self, 'local_compilation') and 
                            isinstance(self.local_compilation, dict) and 
                            self.local_compilation.get('auto_install_packages', False))
                
                if auto_install:
                    logger.info("Attempting to install required packages...")
                    install_texlive_packages(required_packages)
            
            # Set up environment variables
            env = os.environ.copy()
            
            # Create pdflatex command WITHOUT halt-on-error
            pdflatex_cmd = [
                "pdflatex",
                "-interaction=nonstopmode",  # Continue despite errors
                "-file-line-error",          # Show file and line numbers for errors
                file_name
            ]
            
            # First pass - run pdflatex
            logger.info(f"Compiling {file_name} locally using pdflatex (continue-on-error mode)...")
            result = subprocess.run(
                pdflatex_cmd,
                capture_output=True,
                # Use errors='replace' to handle encoding issues
                text=True,
                encoding='latin-1',
                errors='replace',
                check=False,
                env=env
            )
            
            # Log errors but continue anyway
            if result.returncode != 0:
                logger.warning("LaTeX reported errors but attempting to continue")
                try:
                    errors = extract_latex_errors(result.stdout)
                    for i, error in enumerate(errors[:3], 1):  # Show first 3 errors
                        logger.warning(f"Error {i}: {error}")
                except Exception as e:
                    logger.warning(f"Could not extract errors: {str(e)}")
                    
                logger.info("Continuing compilation despite errors...")
            
            # Check for citations and references
            has_citations = "\\cite{" in content or "\\citep{" in content or "\\citet{" in content
            has_references = "\\ref{" in content or "\\pageref{" in content or "\\eqref{" in content
            
            # Run additional passes if needed
            if has_citations:
                logger.info("Running bibtex for citations...")
                try:
                    bibtex_result = subprocess.run(
                        ["bibtex", base_name],
                        capture_output=True,
                        text=True,
                        encoding='latin-1',
                        errors='replace',
                        check=False,
                        env=env
                    )
                except Exception as e:
                    logger.warning(f"Error running bibtex: {str(e)}")
            
            # Run additional pdflatex passes regardless of errors
            if has_citations or has_references:
                logger.info("Running second pdflatex pass...")
                try:
                    subprocess.run(
                        pdflatex_cmd,
                        capture_output=True,
                        text=True,
                        encoding='latin-1',
                        errors='replace',
                        check=False,
                        env=env
                    )
                except Exception as e:
                    logger.warning(f"Error on second pass: {str(e)}")
                
                logger.info("Running final pdflatex pass...")
                try:
                    result = subprocess.run(
                        pdflatex_cmd,
                        capture_output=True,
                        text=True,
                        encoding='latin-1',
                        errors='replace',
                        check=False,
                        env=env
                    )
                except Exception as e:
                    logger.warning(f"Error on final pass: {str(e)}")
            
            # Check if PDF was created, regardless of validity
            pdf_exists = os.path.exists(pdf_path)
            
            if pdf_exists:
                size_bytes = os.path.getsize(pdf_path)
                size_kb = size_bytes / 1024
                
                # Even small PDFs might be valid with errors
                if size_bytes > 100:  # Just checking it's not completely empty
                    logger.info(f"PDF created: {pdf_path} (Size: {size_kb:.2f} KB)")
                    logger.info("Note: PDF may contain formatting errors due to LaTeX errors")
                    
                    # Open PDF if requested - ensuring the path is absolute
                    if (hasattr(self, 'local_compilation') and 
                        isinstance(self.local_compilation, dict) and 
                        self.local_compilation.get('open_pdf', False)):
                        
                        # Get the absolute path to the PDF
                        abs_pdf_path = os.path.abspath(pdf_path)
                        logger.info(f"Attempting to open PDF: {abs_pdf_path}")
                        
                        try:
                            # Call the _open_pdf method
                            self._open_pdf(abs_pdf_path)
                            logger.info("PDF opened successfully")
                        except Exception as e:
                            logger.error(f"Exception while trying to open PDF: {str(e)}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                        
                    # Return to original directory and report success
                    os.chdir(current_dir)
                    return True
                else:
                    logger.error(f"PDF file created but appears to be empty (Size: {size_kb:.2f} KB)")
            else:
                logger.error("Failed to create any PDF output, even with error-continuation")
                
                # Check the log file for specific fatal errors that prevent PDF creation
                log_file = f"{base_name}.log"
                if os.path.exists(log_file):
                    try:
                        with open(log_file, 'r', encoding='latin-1', errors='replace') as f:
                            log_content = f.read()
                        
                        fatal_patterns = [
                            "Fatal error",
                            "Emergency stop",
                            "TeX capacity exceeded",
                            "No output PDF file produced"
                        ]
                        
                        for pattern in fatal_patterns:
                            if pattern in log_content:
                                logger.error(f"Fatal LaTeX error: {pattern} - This prevents any PDF output")
                                break
                                
                    except Exception as e:
                        logger.warning(f"Could not read log file: {str(e)}")
            
            # Return to original directory
            os.chdir(current_dir)
            return pdf_exists
        
        except Exception as e:
            logger.error(f"Exception during LaTeX compilation: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Return to original directory
            try:
                os.chdir(current_dir)
            except:
                pass
            
            return False
    
    def _open_pdf(self, pdf_path):
        """
        Enhanced function to open the PDF file with the default PDF viewer
        with improved error handling and debugging
        """
        try:
            import platform
            system = platform.system()
            
            logger.info(f"Attempting to open PDF with system viewer: {pdf_path}")
            
            # Check if the file exists first
            if not os.path.exists(pdf_path):
                logger.error(f"PDF file does not exist at path: {pdf_path}")
                return False
            
            # Check file size
            size_bytes = os.path.getsize(pdf_path)
            if size_bytes < 100:
                logger.warning(f"PDF file may be invalid (too small: {size_bytes} bytes)")
                # Continue anyway
            
            # Log more information about the file
            logger.info(f"PDF path: {os.path.abspath(pdf_path)}")
            logger.info(f"File size: {size_bytes} bytes")
            
            # Try to open based on platform
            if system == 'Darwin':  # macOS
                logger.info("Using macOS 'open' command")
                subprocess.run(['open', pdf_path], check=False)
            elif system == 'Windows':
                logger.info("Using Windows os.startfile")
                os.startfile(pdf_path)  # Windows-specific
            else:  # Linux and other Unix-like
                logger.info("Using xdg-open for Linux/Unix")
                
                # First try xdg-open
                try:
                    subprocess.run(['xdg-open', pdf_path], check=False)
                except FileNotFoundError:
                    # Try alternative viewers
                    viewers = ['evince', 'okular', 'atril', 'firefox', 'google-chrome']
                    success = False
                    
                    for viewer in viewers:
                        try:
                            subprocess.run([viewer, pdf_path], check=False)
                            logger.info(f"Opened PDF with {viewer}")
                            success = True
                            break
                        except FileNotFoundError:
                            continue
                    
                    if not success:
                        logger.error("Could not find any suitable PDF viewer. Please install one.")
                        return False
            
            logger.info("PDF viewer command executed successfully")
            return True
                    
        except Exception as e:
            logger.error(f"Error opening PDF: {str(e)}")
            
            # More detailed error information
            import traceback
            logger.error(f"Error details: {traceback.format_exc()}")
            
            return False
            
    def trigger_compilation(self):
        """Trigger compilation of the Overleaf project via API"""
        try:
            project_id = self.overleaf_api.get('project_id')
            api_token = self.overleaf_api.get('api_token')
            
            if not (project_id and api_token):
                logger.warning("Missing Overleaf API credentials. Cannot trigger compilation.")
                return
                
            import requests
            
            # Overleaf API endpoints - try multiple endpoints
            api_endpoints = [
                f"https://www.overleaf.com/api/project/{project_id}/compile",  # V1 public
                f"https://www.overleaf.com/api/v2/project/{project_id}/compile",  # V2 public
                f"https://api.overleaf.com/api/v2/project/{project_id}/compile",  # V2 dedicated
                f"https://api.overleaf.com/api/v1/project/{project_id}/compile"   # V1 dedicated
            ]
            
            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # Data needed for compilation request
            data = {
                "draft": False,
                "check": "silent"
            }
            
            # Additional debug logging
            logger.info(f"Using Project ID: {project_id}")
            logger.info("Triggering Overleaf compilation...")
            
            # Try each endpoint until one works
            success = False
            for endpoint in api_endpoints:
                try:
                    logger.info(f"Attempting compilation with endpoint: {endpoint}")
                    response = requests.post(endpoint, headers=headers, json=data, timeout=10)
                    
                    if response.status_code == 200:
                        logger.info(f"Compilation triggered successfully with {endpoint}!")
                        success = True
                        break
                    else:
                        logger.warning(f"Endpoint {endpoint} failed. Status code: {response.status_code}")
                        logger.warning(f"Response: {response.text}")
                except requests.RequestException as e:
                    logger.warning(f"Request to {endpoint} failed: {str(e)}")
                    continue
            
            if not success:
                logger.error("All compilation endpoints failed. Check API token and project ID.")
                logger.info("You may need to manually trigger compilation in the Overleaf interface.")
                
        except ImportError:
            logger.error("Requests library not installed. Install with 'pip install requests'")
        except Exception as e:
            logger.error(f"Error triggering compilation: {str(e)}")


    def monitor_remote_changes(self, check_interval=60):
        """
        Continuously monitor remote repository for changes and pull them when detected.
        
        Args:
            check_interval: Time in seconds between remote checks
        """
        import threading
        
        def remote_checker():
            logger.info(f"Starting remote change monitoring (checking every {check_interval} seconds)...")
            send_log(f"Starting remote change monitoring (checking every {check_interval} seconds)...", level=0)
            while True:
                if os.environ.get('LATEX_COLAB_AGENT_STREAMING', False) == 'True':
                    continue

                try:
                    # Change to git repo directory
                    original_dir = os.getcwd()
                    os.chdir(self.git_repo_path)
                    
                    # Fetch the latest changes without merging
                    logger.debug("Fetching remote changes...")
                    subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
                    
                    # Check if there are changes to pull
                    result = subprocess.run(
                        ["git", "rev-list", "HEAD..origin/master", "--count"],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    
                    # If there are commits to pull
                    if int(result.stdout.strip()) > 0:
                        logger.info(f"Detected {result.stdout.strip()} new commit(s) on Overleaf")
                        send_log(f"Detected {result.stdout.strip()} new commit(s) on Overleaf", level=0)
                        
                        # Check if there are uncommitted local changes
                        status_result = subprocess.run(
                            ["git", "status", "--porcelain"],
                            check=True,
                            capture_output=True,
                            text=True
                        )
                        
                        if status_result.stdout.strip():
                            # There are local changes - stash them
                            logger.info("Local uncommitted changes found. Stashing before pull.")
                            send_log("Local uncommitted changes found. Stashing before pull.", level=0)
                            subprocess.run(["git", "stash"], check=True, capture_output=True)
                            had_local_changes = True
                        else:
                            had_local_changes = False
                        
                        # Pull the changes
                        logger.info("Pulling changes from Overleaf...")
                        send_log("Pulling changes from Overleaf...", level=0)
                        pull_result = subprocess.run(
                            ["git", "pull", "origin", "master"],
                            check=True,
                            capture_output=True,
                            text=True
                        )
                        logger.info("Changes pulled successfully")
                        send_log("Changes pulled successfully", level=0)
                        
                        # If we stashed local changes, try to apply them back
                        if had_local_changes:
                            try:
                                logger.info("Applying stashed local changes...")
                                send_log("Applying stashed local changes...", level=0)
                                subprocess.run(["git", "stash", "pop"], check=True, capture_output=True)
                                logger.info("Local changes reapplied")
                                send_log("Local changes reapplied", level=0)
                            except subprocess.CalledProcessError:
                                logger.warning("Conflict detected when applying local changes")
                                logger.warning("Please resolve conflicts manually in the repository")
                                send_box("Conflict detected when applying local changes. Please resolve conflicts manually in the repository", level=0)
                        
                        # Update the local file with changes from git repo
                        self.update_local_file()
                    
                    # Return to original directory
                    os.chdir(original_dir)
                    
                except Exception as e:
                    logger.error(f"Error checking for remote changes: {str(e)}")
                    send_box(f"Error checking for remote changes: {str(e)}. Check for and remove .git/index.lock", level=0)
                    # Make sure we're back in the original directory
                    try:
                        os.chdir(original_dir)
                    except:
                        pass
                
                # Wait for the next check
                time.sleep(check_interval)
        
        # Start the remote checker in a background thread
        checker_thread = threading.Thread(target=remote_checker, daemon=True)
        checker_thread.start()
        
        return checker_thread

    def monitor_remote_changes_git(self, check_interval=60):
        """
        Continuously monitor remote repository for changes and pull them when detected.
        Uses GitPython library for Git operations.
        
        Args:
            check_interval: Time in seconds between remote checks
        """

        def remote_checker():
            logger.info(f"Starting remote change monitoring using GitPython (checking every {check_interval} seconds)...")
            
            # Initialize the repo object
            try:
                repo = git.Repo(self.git_repo_path)
            except git.InvalidGitRepositoryError:
                logger.error(f"Not a valid git repository: {self.git_repo_path}")
                return
            except Exception as e:
                logger.error(f"Error opening git repository: {str(e)}")
                return
            
            while True:
                if os.environ.get('LATEX_COLAB_AGENT_STREAMING', False) == 'True':
                    continue
                    
                try:
                    # Store original directory
                    original_dir = os.getcwd()
                    os.chdir(self.git_repo_path)
                    
                    # Get origin remote
                    origin = repo.remotes.origin
                    
                    # Fetch latest changes
                    logger.debug("Fetching remote changes...")
                    origin.fetch()
                    
                    # Get the local and remote references
                    local_head = repo.heads.master  # Or 'main' depending on branch name
                    remote_head = repo.refs['origin/master']  # Or 'origin/main'
                    
                    # Check if remote is ahead of local
                    commits_behind = sum(1 for c in repo.iter_commits(f"{local_head}..{remote_head}"))
                    
                    if commits_behind > 0:
                        logger.info(f"Detected {commits_behind} new commit(s) on Overleaf")
                        
                        # Check for local changes
                        if repo.is_dirty(untracked_files=True):
                            logger.info("Local uncommitted changes found. Stashing before pull.")
                            # Create a stash
                            repo.git.stash('save', f"Auto-stash before pull at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                            had_local_changes = True
                        else:
                            had_local_changes = False
                        
                        # Pull changes
                        logger.info("Pulling changes from Overleaf...")
                        try:
                            pull_info = origin.pull()
                            logger.info(f"Changes pulled successfully: {pull_info[0].note}")
                            
                            # Pop the stash if we had local changes
                            if had_local_changes:
                                try:
                                    logger.info("Applying stashed local changes...")
                                    repo.git.stash('pop')
                                    logger.info("Local changes reapplied")
                                except git.GitCommandError as e:
                                    if "conflict" in str(e).lower():
                                        logger.warning("Conflict detected when applying local changes")
                                        logger.warning("Please resolve conflicts manually in the repository")
                                    else:
                                        logger.error(f"Error applying stashed changes: {str(e)}")
                            
                            # Update the local file with changes from git repo
                            self.update_local_file()
                        except git.GitCommandError as e:
                            logger.error(f"Git pull failed: {str(e)}")
                    
                    # Return to original directory
                    os.chdir(original_dir)
                    
                except Exception as e:
                    logger.error(f"Error checking for remote changes: {str(e)}")
                    import traceback
                    logger.debug(f"Traceback: {traceback.format_exc()}")
                    
                    # Make sure we're back in the original directory
                    try:
                        os.chdir(original_dir)
                    except:
                        pass
                
                # Wait for the next check
                time.sleep(check_interval)
        
        # Start the remote checker in a background thread
        checker_thread = threading.Thread(target=remote_checker, daemon=True)
        checker_thread.start()
        
        return checker_thread
    
    @staticmethod
    def write_with_lock(filepath, content, max_attempts=5, retry_delay=1):
        filepath = Path(filepath)
        lock_path = filepath.with_suffix(filepath.suffix + ".lock")
        
        attempt = 0
        while attempt < max_attempts:
            lock_file = open(lock_path, 'w')
            try:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Lock acquired, write the file
                    with open(filepath, 'w') as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    return  # Successfully wrote the file
                except BlockingIOError:
                    # Lock couldn't be acquired
                    attempt += 1
                    if attempt >= max_attempts:
                        raise TimeoutError(f"Could not acquire lock for {filepath} after {max_attempts} attempts")
                    print(f"Lock already held, retrying in {retry_delay} seconds (attempt {attempt}/{max_attempts})")
                    time.sleep(retry_delay)
            finally:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                except:
                    pass  # Ignore errors when releasing a lock we might not have
                lock_file.close()
                if os.path.exists(lock_path):
                    try:
                        os.remove(lock_path)
                    except:
                        pass  # Ignore errors when removing the lock file


    def update_local_file(self):
        """Update the local file with content from the git repository"""
        try:
            file_name = os.path.basename(self.file_path)
            repo_file_path = os.path.join(self.git_repo_path, file_name)
            
            # If the repository file exists, copy it to the local path
            if os.path.exists(repo_file_path):
                # Read content from repo file
                with open(repo_file_path, 'r', encoding='utf-8') as repo_file:
                    content = repo_file.read()

                self.write_with_lock(self.file_path, content) if content else None
                
                #if len(content) > 100:
                    # Write to local file
                #with open(self.file_path, 'w', encoding='utf-8') as local_file:
                #    local_file.write(content)
                    
                os.environ['LATEX_PULLED'] = 'True'
                logger.info(f"Updated local file {self.file_path} with changes from Overleaf")
                send_box(f"Updated local file {self.file_path} with changes from Overleaf", title="Updated", level=1)
                
                # Trigger local compilation if enabled
                if hasattr(self, 'local_compilation') and self.local_compilation:
                    try:
                        logger.info("Triggering local compilation after remote update...")
                        self.compile_locally()
                    except Exception as e:
                        logger.error(f"Local compilation after update failed: {str(e)}")
            else:
                logger.warning(f"File {file_name} not found in repository, cannot update local file")
                send_box(f"File {file_name} not found in repository, cannot update local file", title="Error", level=1)
                
        except Exception as e:
            logger.error(f"Error updating local file: {str(e)}")
            send_box(f"Error updating local file: {str(e)}", title="Error", level=1)

    def monitor_remote(self):
        """Determine if remote monitoring should be enabled"""
        # Add any conditions here - for example, only if local compilation is enabled
        return True
    
    def pull_remote_changes(self):
        """
        Pull latest changes from Overleaf on demand.
        Returns True if successful, False otherwise.
        """
        try:
            logger.info("Pulling latest changes from Overleaf...")
            original_dir = os.getcwd()
            os.chdir(self.git_repo_path)
            
            # Fetch latest changes
            fetch_result = subprocess.run(
                ["git", "fetch", "origin"],
                check=False,
                capture_output=True,
                text=True
            )
            
            if fetch_result.returncode != 0:
                logger.error(f"Git fetch failed: {fetch_result.stderr}")
                # Try to refresh credentials if it seems to be an auth issue
                if "Authentication failed" in fetch_result.stderr or "could not read Username" in fetch_result.stderr:
                    self.refresh_git_credentials()
                    fetch_result = subprocess.run(
                        ["git", "fetch", "origin"],
                        check=False,
                        capture_output=True,
                        text=True
                    )
                    if fetch_result.returncode != 0:
                        os.chdir(original_dir)
                        return False
            
            # Check if there are new changes
            result = subprocess.run(
                ["git", "rev-list", "HEAD..origin/master", "--count"],
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.warning(f"Failed to check for new commits: {result.stderr}")
                os.chdir(original_dir)
                return False
            
            # If there are no changes, return early
            if int(result.stdout.strip()) == 0:
                logger.info("No new changes on Overleaf.")
                os.chdir(original_dir)
                return True
            
            # There are changes to pull - implement the pulling logic
            pull_success = self.pull_and_update_changes()
            
            os.chdir(original_dir)
            return pull_success
        
        except Exception as e:
            logger.error(f"Error pulling remote changes: {str(e)}")
            try:
                os.chdir(original_dir)
            except:
                pass
            return False


def setup_overleaf_git(overleaf_git_url, local_path, git_username=None, git_password=None):
    """
    Setup the git repository if it doesn't exist
    """
    # Create a URL with embedded credentials if provided
    if git_username and git_password:
        try:
            # Properly parse and reconstruct the URL
            from urllib.parse import urlparse, urlunparse
            
            # Parse the URL
            parsed_url = urlparse(overleaf_git_url)
            
            # Create a new URL with credentials
            netloc = f"{git_username}:{git_password}@{parsed_url.netloc}"
            
            # Reconstruct the URL with credentials
            credential_url = urlunparse((
                parsed_url.scheme, 
                netloc,
                parsed_url.path,
                parsed_url.params,
                parsed_url.query,
                parsed_url.fragment
            ))
            
            logger.info(f"Created credential URL for authentication")
        except Exception as e:
            logger.error(f"Error creating credential URL: {str(e)}")
            credential_url = overleaf_git_url
    else:
        credential_url = overleaf_git_url
    
    # Configure Git credential helper to store credentials permanently
    try:
        # Set up credential helper globally
        subprocess.run(["git", "config", "--global", "credential.helper", "store"], check=True)
        
        # If credentials provided, store them now using git credential approve
        if git_username and git_password:
            # Extract the host from URL for credential setup
            from urllib.parse import urlparse
            parsed_url = urlparse(overleaf_git_url)
            host = parsed_url.netloc
            
            # Create git credential input
            cred_input = f"url=https://{host}\nusername={git_username}\npassword={git_password}\n"
            
            # Call git credential approve to store credentials
            process = subprocess.Popen(["git", "credential", "approve"], 
                                      stdin=subprocess.PIPE,
                                      universal_newlines=True)
            process.communicate(input=cred_input)
            logger.info("Stored Git credentials in credential helper")
    except Exception as e:
        logger.error(f"Error setting up git credential helper: {str(e)}")
    
    if not os.path.exists(local_path):
        logger.info(f"Cloning Overleaf repository to {local_path}")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # For initial clone, try with and without credentials if needed
        try:
            # First try with credential URL
            subprocess.run(["git", "clone", credential_url, local_path], check=True)
            logger.info("Repository cloned successfully with embedded credentials")
        except subprocess.CalledProcessError:
            # If that fails, try the original URL (git should use credential helper)
            logger.info("Retrying clone with default credentials")
            subprocess.run(["git", "clone", overleaf_git_url, local_path], check=True)
            logger.info("Repository cloned successfully with credential helper")
        
        # Configure repo to use stored credentials
        os.chdir(local_path)
        subprocess.run(["git", "config", "credential.helper", "store"], check=True)
    else:
        logger.info(f"Repository already exists at {local_path}")
        
        # Ensure it's up to date
        os.chdir(local_path)
        
        # Set credential helper for this repo
        subprocess.run(["git", "config", "credential.helper", "store"], check=True)
            
        # Try to pull - credentials should be handled by credential helper now
        try:
            subprocess.run(["git", "pull"], check=True)
            logger.info("Repository updated to latest version")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error pulling latest changes: {str(e)}")
            if git_username and git_password:
                # If credentials provided, update remote URL and try again
                subprocess.run(["git", "remote", "set-url", "origin", credential_url], check=True)
                subprocess.run(["git", "pull"], check=True)
                logger.info("Repository updated after credential update")


def main():
    parser = argparse.ArgumentParser(description='Real-time LaTeX sync with Overleaf via Git')
    parser.add_argument('file_path', help='Path to the LaTeX file to monitor')
    parser.add_argument('--git-url', required=True, help='Overleaf Git repository URL')
    parser.add_argument('--repo-path', default='./overleaf_repo', help='Local path for the git repository')
    
    # Git credentials arguments
    parser.add_argument('--git-username', help='Git username for Overleaf')
    parser.add_argument('--git-password', help='Git password/token for Overleaf')
    parser.add_argument('--prompt-password', action='store_true', 
                        help='Prompt for git password instead of providing it on command line')
    
    # Overleaf API arguments for compilation
    parser.add_argument('--project-id', help='Overleaf project ID for API access')
    parser.add_argument('--api-token', help='Overleaf API token')
    parser.add_argument('--extract-project-id', action='store_true',
                        help='Extract project ID from the git URL')
    
    # Local compilation options
    parser.add_argument('--local-compile', action='store_true',
                        help='Compile LaTeX locally using pdflatex')
    parser.add_argument('--open-pdf', action='store_true',
                        help='Open the PDF after compilation (when using local-compile)')
    parser.add_argument('--auto-install-packages', action='store_true',
                        help='Automatically install missing LaTeX packages')
    
    args = parser.parse_args()
    
    # Handle password prompt if requested
    git_password = args.git_password
    if args.prompt_password:
        git_password = getpass.getpass("Enter your Overleaf git password/token: ")
    
    # Extract project ID from git URL if requested
    project_id = args.project_id
    if args.extract_project_id and args.git_url:
        # Git URLs are typically in the format: https://git.overleaf.com/project_id
        project_id = args.git_url.rstrip('/').split('/')[-1]
        logger.info(f"Extracted project ID: {project_id}")
        send_box(f"Extracted project ID: {project_id}", title='Project ID', level=1)
    
    # Store updated values back to args
    args.git_password = git_password
    args.project_id = project_id
    
    # Setup the git repository with credentials
    setup_overleaf_git(args.git_url, args.repo_path, args.git_username, args.git_password)
    
    # Create event handler and observer
    event_handler = LatexFileHandler(args.file_path, args.repo_path)
    
    # Add API info if provided
    if args.project_id and args.api_token:
        event_handler.overleaf_api = {
            'project_id': args.project_id,
            'api_token': args.api_token
        }
    
    # Configure local compilation if requested
    if args.local_compile:
        event_handler.local_compilation = {
            'enabled': True,
            'open_pdf': args.open_pdf,
            'auto_install_packages': args.auto_install_packages
        }
        logger.info("Local LaTeX compilation enabled")
        
        if args.auto_install_packages:
            logger.info("Automatic package installation enabled")
    
    observer = Observer()

    # In the main function, after creating the observer
    if event_handler.monitor_remote():
        remote_thread = event_handler.monitor_remote_changes(check_interval=10)  # Check every x seconds
        logger.info("Bidirectional synchronization enabled - monitoring for remote changes")
        send_log("Bidirectional synchronization enabled - monitoring for remote changes", level=0)
    
    # Schedule the observer to watch the directory containing the file
    watch_dir = os.path.dirname(os.path.abspath(args.file_path))
    observer.schedule(event_handler, watch_dir, recursive=False)
    
    # Start the observer
    observer.start()
    logger.info(f"Monitoring {args.file_path} for changes. Press Ctrl+C to stop.")
    send_log(f"Monitoring {args.file_path} for changes. Press Ctrl+C to stop.", level=0)
    
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping monitoring...")
        send_log("Stopping monitoring...", level=0)
        observer.stop()
    
    observer.join()


if __name__ == "__main__":
    main()