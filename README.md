# Aplicación de Transferencia de Archivos
Este proyecto tiene como objetivo crear una aplicación de red para transferir archivos entre un cliente y un servidor, utilizando conceptos esenciales de comunicación entre procesos a través de una red. La aplicación sigue una arquitectura cliente-servidor y ofrece dos operaciones principales: UPLOAD (carga) y DOWNLOAD (descarga).

## Hipótesis y Supuestos
* Si no se recibe respuesta al "handshake request" en un tiempo determinado, se cierra la conexión.
* En caso de fallar el checksum del archivo al finalizar la descarga/subida, se avisa y se cierra el programa, sin intentar nuevamente la operación.

## Implementación
La aplicación utiliza un formato de mensaje que permite la comunicación entre cliente y servidor. Cada mensaje está dividido en cuatro segmentos:

* TYPE: 3 bits para determinar el tipo de mensaje.
* LENGTH: 13 bits para determinar el largo del payload, máximo de 8192 bytes.
* POS: Dependiendo del tipo de mensaje:
  * UPLOAD: Número de paquete inicial (aleatorio).
  * OK: Número de paquete actual.
  * ACK: Número del último paquete entregado correctamente.
  * FIN: Número del paquete final.
* PAYLOAD: Datos del archivo a transferir. También contiene otros datos según el tipo de mensaje, como el nombre del archivo, el hash MD5 del archivo al finalizar la descarga/subida, o el código de error en caso de error.
Una vez establecido el "handshake", se inicia la transferencia de datos. Para ello, el cliente envía mensajes tipo OK con el número de paquete correspondiente, y el servidor responde con ACK confirmando la recepción del paquete. Al finalizar la transferencia, el cliente envía un mensaje tipo FIN con el hash MD5 del archivo, y el servidor verifica la integridad del archivo.

Se ofrecen dos protocolos de transferencia: Stop and Wait y Selective Repeat. La principal diferencia radica en cómo se manejan los paquetes recibidos:

* Stop and Wait: Recibe los paquetes uno a uno y espera el ACK del próximo paquete antes de enviar el siguiente.
* Selective Repeat: Recibe varios paquetes simultáneamente y utiliza una ventana deslizante y un buffer para manejarlos. Esto permite manejar paquetes que llegan en distinto orden o que se pierden.

## Uso
### Servidor
`python star-server.py -t <protocol_type> -p <port_number>`

* protocol_type: Tipo de protocolo de comunicación a utilizar (sw para Stop and Wait, sr para Selective Repeat).
* port_number: Número de puerto en el que el servidor escuchará las conexiones.

### Cliente (Descarga)
`python download.py -t <protocol_type> -H <server_address> -p <port_number> -n <file_name>`

* protocol_type: Tipo de protocolo de comunicación a utilizar (sw para Stop and Wait, sr para Selective Repeat).
* server_address: Dirección IP del servidor.
* port_number: Número de puerto del servidor.
* file_name: Nombre del archivo a descargar.

Crear environment de python en root del proyecto (version 3.11.5):<br/>
`$ python3.11 -m venv env`

Activar environment env:<br/>
`$ source env/bin/activate`

Descargar paquete externo tqdm (dentro de env):<br/>
`(env) $ pip install tqdm`

Crear topolgia de mininet (10% packet loss):<br/>
`(env) $ sudo mn --topo single,3 --link tc,loss=10`

Abrir terminales para cada host en mininet:<br/>
`mininet> xterm h1 h2 h3`

Activar environment en cada host h1, h2 y h3 en mininet:<br/>
`mininet> source env/bin/activate`

Ejecucion server mininet en host h1 (Stop & Wait):<br/>
`(env) $ python start-server -H 10.0.0.1`

Ejecucion server mininet en host h1 (Selective Repeat):<br/>
`(env) $ python start-server -H 10.0.0.1 -t sr`

Ejecucion download (image.png dentro de /storage) mininet en host h2 y h3 (Stop & Wait):<br/>
`(env) $ python download -H 10.0.0.1 -n image.png`

Ejecucion download (image.png dentro de /storage) mininet en host h2 y h3 (Selective Repeat):<br/>
`(env) $ python download -H 10.0.0.1 -n image.png -t sr`

Ejecucion upload (image.png en root) mininet en host h2 y h3 (Stop & Wait):<br/>
`(env) $ python upload -H 10.0.0.1 -s .. -n image.png`

Ejecucion upload (image.png en root) mininet en host h2 y h3 (Selective Repeat):<br/>
`(env) $ python upload -H 10.0.0.1 -s .. -n image.png -t sr`


