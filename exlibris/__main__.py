"""Start Ex Libris: the library app (8080), the public view (8081, unless
EXLIBRIS_PUBLIC=off) and the background tasks, in one process."""
import asyncio
import logging
import os
import signal
import threading
import uvicorn
from exlibris import __version__, config
from exlibris.core import db, tasks


def build_servers():
    from exlibris.web import library, public
    host = os.environ.get("EXLIBRIS_HOST", "0.0.0.0")
    apps = [(library.app, int(os.environ.get("EXLIBRIS_PORT", "8080")))]
    if config.settings().public:
        apps.append((public.app, int(os.environ.get("EXLIBRIS_PUBLIC_PORT", "8081"))))
    return [uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info", proxy_headers=True,
                                          forwarded_allow_ips="*", server_header=False)) for app, port in apps]


async def serve(servers):
    await asyncio.gather(*(s.serve() for s in servers))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log = logging.getLogger("exlibris")
    db.init()
    servers = build_servers()
    log.info("Ex Libris %s — library on :%s%s, data in %s", __version__, servers[0].config.port,
             f", public view on :{servers[1].config.port}" if len(servers) > 1 else " (public view off)",
             config.settings().data_dir)
    stop = threading.Event()
    worker = threading.Thread(target=tasks.run_forever, args=(stop,), name="tasks", daemon=True)
    worker.start()

    def shutdown(*_):
        stop.set()
        for s in servers:
            s.should_exit = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    asyncio.run(serve(servers))
    stop.set()


if __name__ == "__main__":
    main()
