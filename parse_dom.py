from bs4 import BeautifulSoup

with open("d:\\agente-powerbi\\dom_dump.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

for text in ["Mes", "Supervisor", "Nro. Visita"]:
    print(f"\n--- Buscando: {text} ---")
    elements = soup.find_all(string=lambda s: s and text in s)
    for el in elements:
        parent = el.parent
        # Go up until we find a visual-container or similar
        curr = parent
        path = []
        for _ in range(5):
            if curr and curr.name:
                classes = ".".join(curr.get("class", []))
                path.append(f"{curr.name}({classes})")
                curr = curr.parent
            else:
                break
        path.reverse()
        print(" -> ".join(path))
        print(" TEXT:", repr(el))
