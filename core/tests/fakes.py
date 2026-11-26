from core.media import ImageStorage, ImageStorageError, ImageStorageNotConfigured


class FakeImageStorage(ImageStorage):
    """Almacenamiento en memoria para tests: no sale a la red."""

    uploaded = []
    deleted = []
    configured = True
    fail_upload = False
    fail_delete = False
    counter = 0

    @classmethod
    def reset(cls):
        cls.uploaded, cls.deleted = [], []
        cls.configured, cls.fail_upload, cls.fail_delete, cls.counter = True, False, False, 0

    def upload(self, file, folder):
        if not self.configured:
            raise ImageStorageNotConfigured('sin configurar')
        if self.fail_upload:
            raise ImageStorageError('falló')
        type(self).counter += 1
        key = f'{folder}/img{type(self).counter}'
        type(self).uploaded.append((key, file.read()))
        return key

    def delete(self, key):
        if not self.configured:
            raise ImageStorageNotConfigured('sin configurar')
        if self.fail_delete:
            raise ImageStorageError('falló')
        type(self).deleted.append(key)

    def url(self, key, width=None, height=None):
        size = f'{width}x{height}/' if (width or height) else ''
        return f'https://fake.test/{size}{key}'
