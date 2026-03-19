class PhotonServerError(Exception):
    """Raised when the upstream Photon server returns a non-zero return code."""

    pass


class GameManagerError(Exception):
    pass


class GameDoesNotExistError(GameManagerError):
    pass
