class ErrorAplicacion(Exception):
    pass


class ErrorNegocio(ErrorAplicacion):
    pass


class NoEncontrado(ErrorAplicacion):
    pass


class IntegridadError(ErrorAplicacion):
    pass


class NoAutorizado(ErrorAplicacion):
    pass
