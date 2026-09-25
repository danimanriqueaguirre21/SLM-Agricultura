from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.entities.agricultor import Agricultor
from app.domain.valueObjects.email import Email
from app.domain.valueObjects.hash_contrasena import HashContrasena


@dataclass(frozen=True)
class DatosAutenticacionAgricultor:
    id_usuario: str
    id_agricultor: str | None
    rol: str
    nombre: str
    email: Email
    hash_contrasena: HashContrasena
    estado: str


class PuertoRepositorioAgricultor(ABC):
    @abstractmethod
    def existe_por_correo(self, email: Email) -> bool:
        """Indica si existe un usuario con el correo, cualquiera sea su rol."""

    @abstractmethod
    def buscar_por_correo(self, email: Email) -> DatosAutenticacionAgricultor | None:
        """Obtiene las credenciales y el perfil asociado, si existe."""

    @abstractmethod
    def guardar(self, agricultor: Agricultor) -> None:
        """Registra usuario y agricultor y asigna el ID persistido del agricultor."""

    @abstractmethod
    def actualizar_ultimo_acceso(self, id_usuario: str) -> None:
        """Registra un acceso correcto utilizando la identidad del usuario."""
