import re

def valida_email(email):
    """
    Valida um endereço de e-mail.

    Args:
        email (str): O endereço de e-mail a ser validado.

    Returns:
        bool: Se o endereço de e-mail é válido, retorna True; caso contrário, retorna False.
    """

    # Regularização de e-mail (RFC 5322)
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    # Verificar se o endereço de e-mail é válido
    if re.match(pattern, email):
        return True
    else:
        return False

# Exemplos de uso:
print(valida_email("test@example.com"))  # True
print(valida_email("invalid_email"))  # False
print(valida_email("test@example"))  # False (tanto "test" quanto "example" são válidos)
print(valida_email("test@example.com.au"))  # True
