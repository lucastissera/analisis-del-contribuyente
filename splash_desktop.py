"""Pantalla de inicio del portable (.exe) mientras carga el servidor."""



from __future__ import annotations



import sys

import tkinter as tk

from pathlib import Path



MENSAJE_INICIO = "Inicializando, aguarde un momento por favor."

GIF_LOGO = "logo-oscuro-gif demini editado cursor.gif"

COLOR_FONDO = "#000000"

COLOR_TEXTO = "#ffffff"

MARGEN_TEXTO_INFERIOR = 28

MAX_ANCHO_SPLASH = 420

MAX_ALTO_SPLASH = 260

MARGEN_PANTALLA = 20





def _ruta_estatica(nombre: str) -> Path | None:

    candidatos: list[Path] = []

    if getattr(sys, "frozen", False):

        bundle = Path(getattr(sys, "_MEIPASS", ""))

        candidatos.append(bundle / "static" / nombre)

        exe_dir = Path(sys.executable).resolve().parent

        candidatos.append(exe_dir / "static" / nombre)

    raiz = Path(__file__).resolve().parent

    candidatos.append(raiz / "static" / nombre)

    for p in candidatos:

        if p.is_file():

            return p

    return None





def _escalar_dimensiones(ancho: int, alto: int) -> tuple[int, int]:

    if ancho <= MAX_ANCHO_SPLASH and alto <= MAX_ALTO_SPLASH:

        return ancho, alto

    ratio = min(MAX_ANCHO_SPLASH / ancho, MAX_ALTO_SPLASH / alto)

    return max(1, int(ancho * ratio)), max(1, int(alto * ratio))





def _cargar_gif_logo() -> tuple[list, list[int], int, int] | None:

    ruta = _ruta_estatica(GIF_LOGO)

    if ruta is None:

        return None

    try:

        from PIL import Image, ImageTk



        gif = Image.open(ruta)

        fotogramas: list = []

        duraciones: list[int] = []

        ancho = 0

        alto = 0

        while True:

            frame = gif.convert("RGBA")

            if not fotogramas:

                ancho, alto = frame.size

            fotogramas.append(frame)

            duraciones.append(max(int(gif.info.get("duration", 42)), 20))

            gif.seek(gif.tell() + 1)

    except EOFError:

        if fotogramas:

            ancho, alto = _escalar_dimensiones(ancho, alto)

            escalados = [

                ImageTk.PhotoImage(img.resize((ancho, alto), Image.Resampling.LANCZOS))

                for img in fotogramas

            ]

            return escalados, duraciones, ancho, alto

    except Exception:

        return None

    return None





def _cargar_imagen_logo() -> tuple[object, int, int] | None:

    for nombre in ("logo.png", "logo-oscuro.png", "isotipo.png", "favicon-256.png"):

        ruta = _ruta_estatica(nombre)

        if ruta is None:

            continue

        try:

            from PIL import Image, ImageTk



            img = Image.open(ruta).convert("RGBA")

            ancho, alto = _escalar_dimensiones(*img.size)

            if (ancho, alto) != img.size:

                img = img.resize((ancho, alto), Image.Resampling.LANCZOS)

            return ImageTk.PhotoImage(img), ancho, alto

        except Exception:

            try:

                photo = tk.PhotoImage(file=str(ruta))

                ancho, alto = _escalar_dimensiones(photo.width(), photo.height())

                if (ancho, alto) != (photo.width(), photo.height()):

                    factor = max(1, photo.width() // ancho)

                    photo = photo.subsample(factor, factor)

                    ancho, alto = photo.width(), photo.height()

                return photo, ancho, alto

            except Exception:

                continue

    return None





class SplashInicio:

    """Ventana de carga centrada en pantalla."""



    def __init__(self) -> None:

        self.root = tk.Tk()

        self.root.title("Análisis Integral del Contribuyente")

        self.root.configure(bg=COLOR_FONDO)

        self._gif_frames: list = []

        self._gif_durations: list[int] = []

        self._gif_index = 0

        self._anim_id: str | None = None

        self._canvas: tk.Canvas | None = None

        self._img_item: int | None = None

        self._texto_item: int | None = None



        # Mostrar al instante (texto); el GIF se carga en segundo plano.

        ancho, alto = 360, 120

        self._crear_canvas(ancho, alto, None)

        self._ubicar_centro(ancho, alto)

        self.root.after(1, self._cargar_graficos)



    def _cargar_graficos(self) -> None:

        gif = _cargar_gif_logo()

        if gif is not None:

            self._gif_frames, self._gif_durations, ancho, alto = gif

            if self._canvas is not None:

                self._canvas.config(width=ancho, height=alto)

                if self._texto_item is not None:

                    self._canvas.coords(self._texto_item, ancho // 2, alto - MARGEN_TEXTO_INFERIOR)

                    self._canvas.itemconfigure(self._texto_item, width=max(ancho - 40, 180))

                self._ubicar_centro(ancho, alto)

            if self._img_item is None and self._canvas is not None:

                self._img_item = self._canvas.create_image(

                    0, 0, anchor="nw", image=self._gif_frames[0]

                )

                self._canvas.image = self._gif_frames[0]

            elif self._img_item is not None:

                self._canvas.itemconfigure(self._img_item, image=self._gif_frames[0])

                self._canvas.image = self._gif_frames[0]

            self._mostrar_fotograma_gif(0)

            return



        fallback = _cargar_imagen_logo()

        if fallback is not None and self._canvas is not None:

            photo, ancho, alto = fallback

            self._canvas.config(width=ancho, height=alto)

            if self._texto_item is not None:

                self._canvas.coords(self._texto_item, ancho // 2, alto - MARGEN_TEXTO_INFERIOR)

                self._canvas.itemconfigure(self._texto_item, width=max(ancho - 40, 180))

            self._ubicar_centro(ancho, alto)

            if self._img_item is None:

                self._img_item = self._canvas.create_image(0, 0, anchor="nw", image=photo)

            else:

                self._canvas.itemconfigure(self._img_item, image=photo)

            self._canvas.image = photo



    def _crear_canvas(self, ancho: int, alto: int, imagen_inicial) -> None:

        self._canvas = tk.Canvas(

            self.root,

            width=ancho,

            height=alto,

            highlightthickness=0,

            bd=0,

            bg=COLOR_FONDO,

        )

        self._canvas.pack()



        if imagen_inicial is not None:

            self._img_item = self._canvas.create_image(0, 0, anchor="nw", image=imagen_inicial)

            self._canvas.image = imagen_inicial



        self._texto_item = self._canvas.create_text(

            ancho // 2,

            alto - MARGEN_TEXTO_INFERIOR,

            text=MENSAJE_INICIO,

            fill=COLOR_TEXTO,

            font=("Segoe UI", 10),

            width=max(ancho - 40, 180),

            justify="center",

        )



    def _ubicar_centro(self, ancho: int, alto: int) -> None:

        self.root.update_idletasks()

        pantalla_w = self.root.winfo_screenwidth()

        pantalla_h = self.root.winfo_screenheight()

        x = max(0, (pantalla_w - ancho) // 2)

        y = max(0, (pantalla_h - alto) // 2)

        self.root.geometry(f"{ancho}x{alto}+{x}+{y}")

        self.root.update()



    def _mostrar_fotograma_gif(self, indice: int) -> None:

        if self._canvas is None or self._img_item is None or not self._gif_frames:

            return

        self._gif_index = indice % len(self._gif_frames)

        fotograma = self._gif_frames[self._gif_index]

        self._canvas.itemconfigure(self._img_item, image=fotograma)

        self._canvas.image = fotograma

        duracion = self._gif_durations[self._gif_index]

        self._anim_id = self.root.after(duracion, self._siguiente_fotograma_gif)



    def _siguiente_fotograma_gif(self) -> None:

        self._mostrar_fotograma_gif(self._gif_index + 1)



    def actualizar(self) -> None:

        try:

            self.root.update()

        except tk.TclError:

            pass



    def cerrar(self) -> None:

        if self._anim_id is not None:

            try:

                self.root.after_cancel(self._anim_id)

            except Exception:

                pass

            self._anim_id = None

        try:

            self.root.destroy()

        except Exception:

            pass


