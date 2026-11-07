import reflex as rx

config = rx.Config(
    app_name="outdoorsApp",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="light", accent_color="green", radius="large"),
        ),
    ],
    show_built_with_reflex=False,
)
