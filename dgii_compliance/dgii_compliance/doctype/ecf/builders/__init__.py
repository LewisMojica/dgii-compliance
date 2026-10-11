"""Per-type e-CF XML builders.

Each e-CF type has its own module exposing ``build(doc) -> lxml Element`` so it
can be developed, debugged and changed independently.
"""

from . import e31, e32, e43, e44, e45, e46

# Backwards-compatible names (previously defined in new_ecf.py)
build_xml_ecf_E31 = e31.build
build_xml_ecf_E32 = e32.build
build_xml_ecf_E43 = e43.build
build_xml_ecf_E44 = e44.build
build_xml_ecf_E45 = e45.build
build_xml_ecf_E46 = e46.build

BUILDERS = {
	"E31": e31.build,
	"E32": e32.build,
	"E43": e43.build,
	"E44": e44.build,
	"E45": e45.build,
	"E46": e46.build,
}

__all__ = [
	"BUILDERS",
	"build_xml_ecf_E31",
	"build_xml_ecf_E32",
	"build_xml_ecf_E43",
	"build_xml_ecf_E44",
	"build_xml_ecf_E45",
	"build_xml_ecf_E46",
]
