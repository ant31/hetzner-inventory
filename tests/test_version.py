from ant31box.version import Version as Ant31boxVersion
from hetznerinv import __version__ as package_version
from hetznerinv.version import VERSION


def test_version_object_initialization():
    """Test that the VERSION object is initialized correctly."""
    assert VERSION is not None
    assert isinstance(VERSION, Ant31boxVersion)


def test_version_app_version_matches_package_version():
    """Test that VERSION.app_version matches the package's __version__."""
    assert str(VERSION.app_version) == package_version


def test_version_to_dict():
    """Test the to_dict() method of the VERSION object."""
    version_dict = VERSION.to_dict()
    assert isinstance(version_dict, dict)
    assert version_dict["version"] == package_version
    # Check for other keys that ant31box.version.Version might add by default
    assert "python" in version_dict
    assert "version" in version_dict["python"]
    assert "system" in version_dict
    assert "sha" in version_dict # This might be 'N/A' if not in a git repo or git is not found


def test_version_text():
    """Test the text() method of the VERSION object."""
    version_text = VERSION.text()
    assert isinstance(version_text, str)
    # Example: "Running 0.2.2, with CPython 3.12.8, on Linux"
    assert package_version in version_text
    assert "CPython" in version_text # Or whatever implementation is expected
    assert "Linux" in version_text # Or the expected OS
