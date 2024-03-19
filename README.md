# tp1-file-transfer
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


