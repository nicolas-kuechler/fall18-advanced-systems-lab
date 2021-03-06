package ch.ethz.asl.kunicola.thread;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.ClosedByInterruptException;
import java.nio.channels.SelectionKey;
import java.nio.channels.Selector;
import java.nio.channels.SocketChannel;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import java.util.concurrent.BlockingQueue;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import ch.ethz.asl.kunicola.request.AbstractRequest;
import ch.ethz.asl.kunicola.statistic.Statistic;
import ch.ethz.asl.kunicola.util.DecoderUtil;
import ch.ethz.asl.kunicola.util.ServerMessage;

/**
 * Takes a request from the queue, creates the different messages that need to
 * be sent to the memcached server/s and waits for the response. On successful
 * completion of the request the server response is forwarded to the client. In
 * case of an error the client is informed accordingly. Finally the per worker
 * statistics are updated with the request.
 * 
 * @author nicolas-kuechler
 *
 */
public class WorkerThread extends Thread {

	private final Logger LOG = LogManager.getLogger();

	private static final int BUFFER_SIZE = 65536; // 2^16 b enough to handle up to ten 4096b values in multiget
	private static final long STATS_WINDOWS_SIZE = 50000l; // in 100 microseconds -> 5 secs

	private int id = -1;
	private BlockingQueue<AbstractRequest> queue = null;

	private Selector selector = null;
	private SelectionKey[] serverSelectionKeys = null;
	private ByteBuffer[] buffers = null;
	private Statistic statistic = null;
	private long statisticWindowEnd;

	private List<String> mcAddresses = null;

	@Override
	public void run() {
		super.run();
		try {
			while (true) {
				AbstractRequest request;

				request = queue.take();
				long dequeueTime = System.nanoTime() / 100000; // in 100 microseconds
				request.setDequeueTime(dequeueTime);
				LOG.debug("Q>W  {}", request);

				// get messages from request
				ServerMessage[] msgs = request.getServerMessages();

				// send messages to servers
				for (ServerMessage msg : msgs) {
					buffers[0].clear();
					buffers[0].put(msg.getContent());
					buffers[0].flip();

					int serverId = msg.getServerId();
					SocketChannel serverSocketChannel = (SocketChannel) serverSelectionKeys[serverId]
							.channel();

					try {
						while (buffers[0].hasRemaining()) {
							serverSocketChannel.write(buffers[0]);
						}
						long serverStartTime = System.nanoTime() / 100000; // in 100 microseconds
						request.setServerStartTime(serverId, serverStartTime);
						LOG.debug("W>S{}  {}", serverId, msg);
					} catch (ClosedByInterruptException e) {
						throw new InterruptedException();
					} catch (IOException e) {
						LOG.error("Error writing message to server: {}", e.getMessage());
					}
				}

				// reset all buffers
				for (int i = 0; i < buffers.length; i++) {
					buffers[i].clear();
				}

				boolean hasAllServerResponse = false;

				// collect responses for each message
				while (!hasAllServerResponse) {

					Set<SelectionKey> selectedKeys;
					try {
						int updatedChannels = selector.select();

						if (updatedChannels == 0) {
							LOG.debug("No updated channels");
							continue;
						}

						selectedKeys = selector.selectedKeys();

					} catch (ClosedByInterruptException e) {
						throw new InterruptedException();
					} catch (IOException e1) {
						LOG.error("Error selecting channels {}", e1.getMessage());
						continue;
					}

					Iterator<SelectionKey> iterator = selectedKeys.iterator();

					while (iterator.hasNext() && !hasAllServerResponse) {
						SelectionKey selectionKey = iterator.next();
						iterator.remove();

						long serverEndTime = System.nanoTime() / 100000; // in 100 microseconds

						if (!selectionKey.isValid()) {
							throw new RuntimeException("Invalid Selection Key -> Wanted to check if this can happen");
						}

						if (selectionKey.isReadable()) {
							SocketChannel serverSocketChannel = (SocketChannel) selectionKey.channel();
							Integer serverId = (Integer) selectionKey.attachment();

							try {
								int byteCount = serverSocketChannel.read(buffers[serverId]);

								if (byteCount < 1) {
									LOG.debug("number of bytes read: {} (-1 stands for end of stream)", byteCount);
									continue;
								}

								if (LOG.isDebugEnabled()) {
									LOG.debug("W<S{}  {}", serverId, DecoderUtil.decode(buffers[serverId]));
								}
								request.setServerEndTime(serverId, serverEndTime);
								hasAllServerResponse = request.putServerResponse(serverId, buffers[serverId]);

							} catch (ClosedByInterruptException e) {
								throw new InterruptedException();
							} catch (IOException e) {
								LOG.error("Error reading server socket channel: {}", e.getMessage());
							}
						}
					}
				}

				// write message back to client
				ByteBuffer clientResponseBuffer = request.getClientResponseBuffer();

				if (clientResponseBuffer != null) {
					clientResponseBuffer.flip();
					SocketChannel clientSocketChannel = request.getClientSocketChannel();
					try {
						while (clientResponseBuffer.hasRemaining()) {
							clientSocketChannel.write(clientResponseBuffer);
						}
						if (LOG.isDebugEnabled()) {
							LOG.debug("C<W  {}", DecoderUtil.decode(clientResponseBuffer));
						}
					} catch (ClosedByInterruptException e) {
						throw new InterruptedException();
					} catch (IOException e) {
						LOG.error("Error writing response to client: {}", e);
					}
				}

				long processEndTime = System.nanoTime() / 100000; // in 100 microseconds
				request.setProcessEndTime(processEndTime);

				// update statistics
				while ((statisticWindowEnd - processEndTime) < 0) {
					statistic.report();
					statisticWindowEnd += STATS_WINDOWS_SIZE;
					statistic.reset();
				}

				statistic.update(request);
			}

			// before worker ends report a summary

		} catch (InterruptedException e) {
			LOG.info("Worker Interrupted");
			Thread.currentThread().interrupt(); // restore interrupt flag
		} finally {
			statistic.reportWorkerSummary();
		}
	}

	public WorkerThread withId(int id) {
		this.id = id;
		return this;
	}

	public WorkerThread withQueue(BlockingQueue<AbstractRequest> queue) {
		this.queue = queue;
		return this;
	}

	public WorkerThread withMcAddresses(List<String> mcAddresses) {
		this.mcAddresses = mcAddresses;
		return this;
	}

	public WorkerThread withPriority(int priority) {
		setPriority(priority);
		return this;
	}

	public WorkerThread withStatistic(Statistic statistic) {
		this.statistic = statistic;
		return this;
	}

	public WorkerThread withStart(long start) {
		this.statisticWindowEnd = start + 5000;
		return this;
	}

	public WorkerThread withUncaughtExceptionHandler(UncaughtExceptionHandler uncaughtExceptionHandler) {
		setUncaughtExceptionHandler(uncaughtExceptionHandler);
		return this;
	}

	public WorkerThread create() {
		LOG.debug("Creating worker thread " + this.id + "...");

		assert (id != -1);
		assert (queue != null);
		assert (mcAddresses != null);

		try {
			selector = Selector.open();
			serverSelectionKeys = new SelectionKey[mcAddresses.size()];
			buffers = new ByteBuffer[mcAddresses.size()];

			for (int i = 0; i < mcAddresses.size(); i++) {
				String[] mcAddress = mcAddresses.get(i).split(":");
				String ip = mcAddress[0];
				int port = Integer.parseInt(mcAddress[1]);

				SocketChannel socketChannel = SocketChannel.open();
				socketChannel.connect(new InetSocketAddress(ip, port));
				socketChannel.configureBlocking(false);

				SelectionKey selectionKey = socketChannel.register(selector, SelectionKey.OP_READ, i);
				serverSelectionKeys[i] = selectionKey;

				buffers[i] = ByteBuffer.allocate(BUFFER_SIZE);
			}

		} catch (IOException e) {
			LOG.error("Error opening server socket channel: {}", e);
		}

		return this;
	}

}
