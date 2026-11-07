import reflex as rx

config = rx.Config(
    app_name="outdoorsApp",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ],
    show_built_with_reflex=False,
)
