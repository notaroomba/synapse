import asyncio
import websockets

async def handler(websocket):
    print("Unity connected")

    async for message in websocket:
        print("From Unity:", message)

        # optional reply
        await websocket.send("ACK")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket server running on port 8080")
        await asyncio.Future()  # keep alive

asyncio.run(main())
