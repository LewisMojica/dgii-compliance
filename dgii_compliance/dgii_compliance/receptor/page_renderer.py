"""Custom page renderer serving the DGII receptor resource paths.

Registered via the ``page_renderer`` hook so Frappe dispatches
``/fe/recepcion/api/ecf`` and ``/fe/aprobacioncomercial/api/ecf`` to the
handlers in :mod:`endpoints` instead of rendering a website page.
"""

from frappe.website.page_renderers.base_renderer import BaseRenderer

from dgii_compliance.dgii_compliance.receptor import endpoints


class ReceptorPageRenderer(BaseRenderer):
	RECEPCION = "fe/recepcion/api/ecf"
	APROBACION = "fe/aprobacioncomercial/api/ecf"

	def can_render(self):
		return self.path.lower() in (self.RECEPCION, self.APROBACION)

	def render(self):
		if self.path.lower() == self.RECEPCION:
			data, status, headers = endpoints.handle_recepcion()
		else:
			data, status, headers = endpoints.handle_aprobacion()
		return self.build_response(data, status, headers)
