"""Small IntEnum protocol for frozen code, with canonical member identities."""


class WireEnum:
    def __new__(cls, value, name=None):
        if name is None:
            return cls.from_value(value)
        member = object.__new__(cls)
        member.value, member.name = value, name
        return member

    @classmethod
    def from_value(cls, value):
        for member in cls.__dict__.values():
            if isinstance(member, cls) and member.value == value:
                return member
        member = cls._missing_(value)
        if isinstance(member, cls):
            return member
        raise ValueError("Invalid " + cls.__name__ + " value")

    @classmethod
    def _missing_(cls, value):
        return None

    def __int__(self):
        return self.value

    def __index__(self):
        return self.value

    def __eq__(self, other):
        return self.value == (other.value if isinstance(other, WireEnum) else other)

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):
        return self.__class__.__name__ + "." + self.name

    def __str__(self):
        return str(self.value)
