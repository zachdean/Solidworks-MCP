"""
SolidWorks Finder
-----------------
Auto-detect SolidWorks installation on Windows.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# Try to import winreg (Windows only)
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False
    logger.warning("winreg not available - registry search disabled")


class SolidWorksFinder:
    """
    Find SolidWorks installation on the system
    
    Search order:
    1. Windows Registry
    2. Common installation paths
    3. Program Files directory search
    """
    
    # Registry paths to check
    REGISTRY_PATHS = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SolidWorks\SOLIDWORKS") if HAS_WINREG else None,
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\SolidWorks\SOLIDWORKS") if HAS_WINREG else None,
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\SolidWorks\SOLIDWORKS") if HAS_WINREG else None,
    ]
    
    # Common installation paths
    COMMON_PATHS = [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe",
        r"C:\Program Files\SolidWorks Corp\SolidWorks\SLDWORKS.exe",
        r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe",
        r"D:\SolidWorks\SLDWORKS.exe",
        r"E:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe",
    ]
    
    # Template search paths relative to SolidWorks install
    TEMPLATE_SUBDIRS = [
        "data/templates",
        "lang/english/Tutorial",
        "lang/english/templates",
    ]
    
    # Drawing-table template extensions, keyed by this project's own
    # template_type name -- see `_find_table_template`. "bom" was wired up by
    # sw-mio.1; "hole"/"revision"/"weldment" added by sw-mio.3, per
    # docs/api/04-tables.md's Gotchas for InsertHoleTable2/3
    # (`.sldholtbt`, unverified -- inferred by analogy, not independently
    # confirmed for hole tables), ISheet::InsertRevisionTable2 (`.sldrevtbt`),
    # and IView::InsertWeldmentTable (`.sldwldtbt`, confirmed: "the weldment
    # cut-list table template installed with SOLIDWORKS is
    # <install_dir>\\lang\\<language>\\cut list.sldwldtbt").
    TABLE_TEMPLATE_EXTENSIONS = {
        "bom": ".sldbomtbt",
        "hole": ".sldholtbt",
        "revision": ".sldrevtbt",
        "weldment": ".sldwldtbt",
    }

    # ProgramData template paths
    PROGRAMDATA_TEMPLATE_PATHS = [
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2024\templates",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2023\templates",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2022\templates",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS\templates",
    ]
    
    @classmethod
    def find(cls) -> Optional[str]:
        """
        Find SolidWorks executable
        
        Returns:
            Path to SLDWORKS.exe or None if not found
        """
        # Try registry first
        if HAS_WINREG:
            path = cls._find_from_registry()
            if path:
                return path
        
        # Try common paths
        path = cls._find_from_common_paths()
        if path:
            return path
        
        # Search Program Files
        path = cls._search_program_files()
        if path:
            return path
        
        logger.error("SolidWorks installation not found")
        return None
    
    @classmethod
    def _find_from_registry(cls) -> Optional[str]:
        """Search Windows registry for SolidWorks"""
        if not HAS_WINREG:
            return None
        
        for reg_info in cls.REGISTRY_PATHS:
            if reg_info is None:
                continue
            
            hkey, reg_path = reg_info
            try:
                with winreg.OpenKey(hkey, reg_path) as key:
                    versions = cls._get_registry_subkeys(key)
                    versions.sort(reverse=True)  # Latest version first
                    
                    for version in versions:
                        try:
                            with winreg.OpenKey(key, version) as ver_key:
                                sw_path, _ = winreg.QueryValueEx(ver_key, "SolidWorks Exe")
                                if os.path.exists(sw_path):
                                    logger.info(f"Found SolidWorks {version} in registry: {sw_path}")
                                    return sw_path
                        except (WindowsError, FileNotFoundError):
                            continue
            except (WindowsError, FileNotFoundError):
                continue
        
        return None
    
    @classmethod
    def _get_registry_subkeys(cls, key) -> List[str]:
        """Get all subkeys of a registry key"""
        subkeys = []
        i = 0
        while True:
            try:
                subkeys.append(winreg.EnumKey(key, i))
                i += 1
            except WindowsError:
                break
        return subkeys
    
    @classmethod
    def _find_from_common_paths(cls) -> Optional[str]:
        """Check common installation paths"""
        # Add versioned paths dynamically
        all_paths = list(cls.COMMON_PATHS)
        
        for year in range(2030, 2015, -1):
            all_paths.extend([
                rf"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS {year}\SLDWORKS.exe",
                rf"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS {year}\SLDWORKS.exe",
                rf"C:\Program Files\SolidWorks Corp\SolidWorks {year}\SLDWORKS.exe",
            ])
        
        for path in all_paths:
            if os.path.exists(path):
                logger.info(f"Found SolidWorks at: {path}")
                return path
        
        return None
    
    @classmethod
    def _search_program_files(cls) -> Optional[str]:
        """Search Program Files directories for SolidWorks"""
        search_roots = [
            r"C:\Program Files",
            r"D:\Program Files",
            r"E:\Program Files",
            r"C:\Program Files (x86)",
        ]
        
        for root in search_roots:
            if not os.path.exists(root):
                continue
            
            try:
                for folder in os.listdir(root):
                    if "solidworks" in folder.lower():
                        sw_folder = os.path.join(root, folder)
                        # Search for SLDWORKS.exe
                        for dirpath, _, files in os.walk(sw_folder):
                            if "SLDWORKS.exe" in files:
                                path = os.path.join(dirpath, "SLDWORKS.exe")
                                logger.info(f"Found SolidWorks by search: {path}")
                                return path
            except PermissionError:
                continue
        
        return None
    
    @classmethod
    def find_template(cls, template_type: str = "part", sw_exe_path: str = None) -> Optional[str]:
        """
        Find SolidWorks template file

        Args:
            template_type: "part", "assembly", "drawing", or a table-template
                type ("bom" -- see `_find_table_template`)
            sw_exe_path: SolidWorks exe path (auto-detect if None)

        Returns:
            Path to template file or None
        """
        template_files = {
            "part": "Part.prtdot",
            "assembly": "Assembly.asmdot",
            "drawing": "Drawing.drwdot",
        }

        key = template_type.lower()
        template_name = template_files.get(key)
        if template_name is None:
            if key in cls.TABLE_TEMPLATE_EXTENSIONS:
                return cls._find_table_template(key, sw_exe_path)
            logger.error(f"Unknown template type: {template_type}")
            return None

        # Get SolidWorks directory
        if sw_exe_path:
            sw_dir = os.path.dirname(sw_exe_path)
        else:
            sw_exe = cls.find()
            if sw_exe:
                sw_dir = os.path.dirname(sw_exe)
            else:
                sw_dir = None

        # Search relative to SolidWorks install
        if sw_dir:
            for subdir in cls.TEMPLATE_SUBDIRS:
                template_path = os.path.join(sw_dir, subdir, template_name)
                if os.path.exists(template_path):
                    logger.info(f"Found {template_type} template: {template_path}")
                    return template_path

        # Search ProgramData
        for pdata_path in cls.PROGRAMDATA_TEMPLATE_PATHS:
            template_path = os.path.join(pdata_path, template_name)
            if os.path.exists(template_path):
                logger.info(f"Found {template_type} template in ProgramData: {template_path}")
                return template_path

        logger.warning(f"Template not found: {template_type}")
        return None

    @classmethod
    def _find_table_template(cls, template_type: str, sw_exe_path: str = None) -> Optional[str]:
        """Find a default drawing-table template (BOM, revision, weldment
        cut list, ...) by extension, for template types that -- unlike
        part/assembly/drawing -- have no single fixed filename.

        Per docs/api/04-tables.md's `InsertBomTable4`/`6` Gotchas, table
        templates live in `<SOLIDWORKS_install_dir>\\lang\\<language>\\` with
        a type-specific extension (`.sldbomtbt` for BOM, e.g.
        `bom-standard.sldbomtbt`) -- there is no fixed filename to look up the
        way `Part.prtdot`/`Assembly.asmdot`/`Drawing.drwdot` are, so this
        globs each installed language folder under `lang/` for the first
        file with that extension, preferring an "english" locale folder if
        more than one is installed.
        """
        extension = cls.TABLE_TEMPLATE_EXTENSIONS.get(template_type)
        if extension is None:
            logger.error(f"Unknown table template type: {template_type}")
            return None

        if sw_exe_path:
            sw_dir = os.path.dirname(sw_exe_path)
        else:
            sw_exe = cls.find()
            sw_dir = os.path.dirname(sw_exe) if sw_exe else None

        if not sw_dir:
            logger.warning(f"Template not found: {template_type} (SolidWorks install not found)")
            return None

        lang_dir = os.path.join(sw_dir, "lang")
        if not os.path.isdir(lang_dir):
            logger.warning(f"Template not found: {template_type} (no lang dir under {sw_dir})")
            return None

        try:
            locales = sorted(
                os.listdir(lang_dir),
                key=lambda name: (0 if "english" in name.lower() else 1, name.lower()),
            )
        except OSError:
            logger.warning(f"Template not found: {template_type} (could not list {lang_dir})")
            return None

        for locale in locales:
            locale_dir = os.path.join(lang_dir, locale)
            if not os.path.isdir(locale_dir):
                continue
            try:
                filenames = sorted(os.listdir(locale_dir))
            except OSError:
                continue
            for filename in filenames:
                if filename.lower().endswith(extension):
                    template_path = os.path.join(locale_dir, filename)
                    logger.info(f"Found {template_type} template: {template_path}")
                    return template_path

        logger.warning(f"Template not found: {template_type}")
        return None
    
    @classmethod
    def get_version(cls, exe_path: str = None) -> Optional[str]:
        """
        Get SolidWorks version from executable
        
        Args:
            exe_path: Path to SLDWORKS.exe (auto-detect if None)
        
        Returns:
            Version string or None
        """
        if exe_path is None:
            exe_path = cls.find()
        
        if not exe_path or not os.path.exists(exe_path):
            return None
        
        try:
            import win32api
            info = win32api.GetFileVersionInfo(exe_path, "\\")
            ms = info['FileVersionMS']
            ls = info['FileVersionLS']
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        except ImportError:
            logger.debug("win32api not available for version detection")
        except Exception as e:
            logger.debug(f"Could not get version: {e}")
        
        return None
    
    @classmethod
    def get_install_info(cls) -> dict:
        """
        Get comprehensive SolidWorks installation info
        
        Returns:
            Dictionary with installation details
        """
        exe_path = cls.find()
        
        info = {
            "found": exe_path is not None,
            "exe_path": exe_path,
            "version": None,
            "install_dir": None,
            "templates": {
                "part": None,
                "assembly": None,
                "drawing": None,
            }
        }
        
        if exe_path:
            info["install_dir"] = os.path.dirname(exe_path)
            info["version"] = cls.get_version(exe_path)
            info["templates"]["part"] = cls.find_template("part", exe_path)
            info["templates"]["assembly"] = cls.find_template("assembly", exe_path)
            info["templates"]["drawing"] = cls.find_template("drawing", exe_path)
        
        return info


# ============================================================================
# Convenience Functions
# ============================================================================

def find_solidworks() -> Optional[str]:
    """Find SolidWorks executable"""
    return SolidWorksFinder.find()


def find_template(template_type: str = "part") -> Optional[str]:
    """Find SolidWorks template"""
    return SolidWorksFinder.find_template(template_type)


def get_solidworks_info() -> dict:
    """Get SolidWorks installation info"""
    return SolidWorksFinder.get_install_info()
