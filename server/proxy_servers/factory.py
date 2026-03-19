class PhotonProxyFactory:
    @staticmethod
    def create_tunnel(
        local_port: int, remote_ip: str, remote_port: int
    ) -> "PhotonQueueClient":
        from server.photon.queue.photon_queue_client import PhotonQueueClient

        return PhotonQueueClient(remote_ip, remote_port)
