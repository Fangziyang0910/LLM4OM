"""Cooperative task supervision through the public Method and SDK token contracts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest

from llm4om import CancellationToken
from llm4om.contracts import RunError
from llm4om.methods import DirectFactory, MethodContext
from llm4om.plugins import MethodPlugin


class AsyncControlTests(unittest.TestCase):
    def test_method_cancellation_awaits_cleanup_before_returning(self):
        entered, cleaned = Event(), Event()
        class Method:
            async def run(self, problem, context, *, checkpoint=None):
                entered.set()
                try:
                    await asyncio.sleep(30)
                finally:
                    await asyncio.sleep(0)
                    cleaned.set()
        class Factory:
            def create(self, config):
                return Method()
        manifest = DirectFactory().describe()
        plugin = MethodPlugin(manifest, {'kind': 'fixture'}, Factory())
        token = CancellationToken()
        context = MethodContext(None, {}, {}, 'synthetic', token)
        with ThreadPoolExecutor(1) as pool:
            work = pool.submit(plugin.run, {}, {}, context)
            self.assertTrue(entered.wait(2))
            token.cancel()
            with self.assertRaises(RunError) as caught:
                work.result(timeout=2)
        self.assertEqual(caught.exception.code, 'run_cancelled')
        self.assertTrue(cleaned.is_set())

    def test_method_systemexit_is_a_diagnostic_not_a_process_exit(self):
        class Method:
            async def run(self, problem, context, *, checkpoint=None):
                raise SystemExit(7)
        class Factory:
            def create(self, config):
                return Method()
        plugin = MethodPlugin(DirectFactory().describe(), {'kind': 'fixture'}, Factory())
        with self.assertRaises(RunError) as caught:
            plugin.run({}, {}, MethodContext(None, {}, {}, 'synthetic'))
        self.assertEqual(caught.exception.code, 'method_error')
        self.assertEqual(caught.exception.details['exception_type'], 'SystemExit')

if __name__ == '__main__':
    unittest.main()
