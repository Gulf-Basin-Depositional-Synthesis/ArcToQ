def classFactory(iface):
    """Load ArcToQPlugin class from file ArcToQPlugin."""
    from .arctoq_plugin import ArcToQPlugin
    return ArcToQPlugin(iface)