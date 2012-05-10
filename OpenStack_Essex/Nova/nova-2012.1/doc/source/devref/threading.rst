Threading model
===============

All OpenStack services use *green thread* model of threading, implemented
through using the Python `eventlet <http://eventlet.net/>`_ and
`greenlet <http://packages.python.org/greenlet/>`_ libraries.

Green threads use a cooperative model of threading: thread context
switches can only occur when specific eventlet or greenlet library calls are
made (e.g., sleep, certain I/O calls). From the operating system's point of
view, each OpenStack service runs in a single thread.

The use of green threads reduces the likelihood of race conditions, but does
not completely eliminate them. In some cases, you may need to use the
``@utils.synchronized(...)`` decorator to avoid races.

In addition, since there is only one operating system thread, a call that
blocks that main thread will block the entire process.

Yielding the thread in long-running tasks
-----------------------------------------
If a code path takes a long time to execute and does not contain any methods
that trigger an eventlet context switch, the long-running thread will block
any pending threads.

This scenario can be avoided by adding calls to the eventlet sleep method
in the long-running code path. The sleep call will trigger a context switch
if there are pending threads, and using an argument of 0 will avoid introducing
delays in the case that there is only a single green thread::

	from eventlet import greenthread
	...
	greenthread.sleep(0)


MySQL access and eventlet
-------------------------
Queries to the MySQL database will block the main thread of a service. This is
because OpenStack services use an external C library for accessing the MySQL
database. Since eventlet cannot use monkey-patching to intercept blocking
calls in a C library, the resulting database query blocks the thread.

The Diablo release contained a thread-pooling implementation that did not
block, but this implementation resulted in a `bug`_ and was removed.

See this `mailing list thread`_ for a discussion of this issue, including
a discussion of the `impact on performance`_.

.. _bug: https://bugs.launchpad.net/nova/+bug/838581
.. _mailing list thread: https://lists.launchpad.net/openstack/msg08118.html
.. _impact on performance: https://lists.launchpad.net/openstack/msg08217.html
