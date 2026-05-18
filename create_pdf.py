import os

def create_pdf(path):
    # Minimal PDF structure (ASCII only for simplicity/compatibility)
    # Using 1-based indexing for objects in this simple manual build
    # 1: Catalog, 2: Pages, 3: Page, 4: Font, 5: Contents
    
    header = b"%PDF-1.1\n"
    
    obj1 = b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
    obj3 = b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R>>\nendobj\n"
    obj4 = b"4 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"
    
    content_stream = (
        "BT\n"
        "/F1 18 Tf\n72 720 Td\n(Sistema de puntos de la Quiniela Mundial 2026) Tj\n"
        "0 -40 Td\n/F1 12 Tf\n"
        "(1) Fase de grupos: Puntos por resultados y marcadores exactos. Tj\n"
        "0 -25 Td (2) Eliminatorias: Puntos por acertar que equipo avanza. Tj\n"
        "0 -25 Td (3) Resultado exacto en eliminatorias: Puntos extra por marcador. Tj\n"
        "0 -25 Td (4) Posicion final del torneo: Puntos por campeon y subcampeon. Tj\n"
        "0 -25 Td (5) Premios individuales: Puntos por goleador y mejor jugador. Tj\n"
        "0 -50 Td (Nota: Los puntos de llaves solo cuentan con resultados reales o) Tj\n"
        "0 -15 Td (si el usuario elige explicitamente quien avanza.) Tj\n"
        "ET"
    ).encode('ascii')
    
    obj5 = b"5 0 obj\n<</Length " + str(len(content_stream)).encode('ascii') + b">>\nstream\n" + content_stream + b"\nendstream\nendobj\n"
    
    objs = [obj1, obj2, obj3, obj4, obj5]
    offsets = []
    current_offset = len(header)
    
    body = header
    for obj in objs:
        offsets.append(current_offset)
        body += obj
        current_offset += len(obj)
    
    xref_start = current_offset
    xref = b"xref\n0 " + str(len(objs) + 1).encode('ascii') + b"\n"
    xref += b"0000000000 65535 f \n"
    for o in offsets:
        xref += f"{o:010d} 00000 n \n".encode('ascii')
    
    trailer = (
        f"trailer\n<</Size {len(objs)+1} /Root 1 0 R>>\n"
        f"startxref\n{xref_start}\n%%EOF"
    ).encode('ascii')
    
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(body)
        f.write(xref)
        f.write(trailer)
    
    print(f"File created: {path}")
    print(f"Size: {os.path.getsize(path)} bytes")

target_path = r'c:\Users\gamad\OneDrive\Escritorio\quiniela\static\inicio\docs\sistema_puntos_quiniela.pdf'
create_pdf(target_path)
