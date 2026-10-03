"""Coarse device information only; never retain the original User-Agent."""


def short_user_agent(value: str | None) -> str:
    agent = (value or "").lower()
    os_name = next(
        (
            name
            for marker, name in (
                ("windows", "Windows"),
                ("android", "Android"),
                ("iphone", "iOS"),
                ("ipad", "iOS"),
                ("mac os", "macOS"),
                ("linux", "Linux"),
            )
            if marker in agent
        ),
        "Неизвестно",
    )
    browser = next(
        (
            name
            for marker, name in (
                ("edg/", "Edge"),
                ("firefox/", "Firefox"),
                ("chrome/", "Chrome"),
                ("safari/", "Safari"),
            )
            if marker in agent
        ),
        "Неизвестно",
    )
    device = "Телефон" if "mobile" in agent else "Планшет" if "tablet" in agent else "Компьютер"
    return f"{os_name} / {browser} / {device}"
