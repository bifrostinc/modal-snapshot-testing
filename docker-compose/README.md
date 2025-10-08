docker-compose on  conor/docker-compose-repro
✦ at 09:04:59 → uv run python run-docker-compose.py "niteshift/sandbox-docker-image@sha256:968397af43265ac5fdff9efa9d65e4a0c4336c104a5067771bde96cbfd13a419" docker-compose.yml
Looking up modal.Sandbox app
Creating sandbox
Copying docker-compose file to sandbox
Running docker-compose up
Attaching to niteshift-redis
docker-compose up failed:
 redis Pulling
 0368fd46e3c6 Pulling fs layer
 98ea1731a89c Pulling fs layer
 8d33c6a288b6 Pulling fs layer
 9f65a51c3904 Pulling fs layer
 e6f15f52e943 Pulling fs layer
 ba6b3bb28d19 Pulling fs layer
 4f4fb700ef54 Pulling fs layer
 98049c578bdc Pulling fs layer
 9f65a51c3904 Waiting
 e6f15f52e943 Waiting
 4f4fb700ef54 Waiting
 ba6b3bb28d19 Waiting
 98049c578bdc Waiting
 0368fd46e3c6 Downloading [>                                                  ]  36.46kB/3.638MB
 8d33c6a288b6 Downloading [>                                                  ]  2.738kB/173.2kB
 8d33c6a288b6 Verifying Checksum
 8d33c6a288b6 Download complete
 98ea1731a89c Downloading [==================================================>]     951B/951B
 98ea1731a89c Verifying Checksum
 98ea1731a89c Download complete
 0368fd46e3c6 Downloading [======================================>            ]  2.834MB/3.638MB
 e6f15f52e943 Downloading [>                                                  ]  150.6kB/14.7MB
 0368fd46e3c6 Verifying Checksum
 0368fd46e3c6 Download complete
 0368fd46e3c6 Extracting [>                                                  ]  65.54kB/3.638MB
 0368fd46e3c6 Extracting [==================================================>]  3.638MB/3.638MB
 ba6b3bb28d19 Downloading [==================================================>]      99B/99B
 ba6b3bb28d19 Verifying Checksum
 ba6b3bb28d19 Download complete
 e6f15f52e943 Downloading [====================================>              ]  10.62MB/14.7MB
 0368fd46e3c6 Pull complete
 98ea1731a89c Extracting [==================================================>]     951B/951B
 98ea1731a89c Extracting [==================================================>]     951B/951B
 98ea1731a89c Pull complete
 8d33c6a288b6 Extracting [=========>                                         ]  32.77kB/173.2kB
 8d33c6a288b6 Extracting [==================================================>]  173.2kB/173.2kB
 8d33c6a288b6 Extracting [==================================================>]  173.2kB/173.2kB
 9f65a51c3904 Downloading [>                                                  ]  10.51kB/1.003MB
 9f65a51c3904 Verifying Checksum
 9f65a51c3904 Download complete
 4f4fb700ef54 Downloading [==================================================>]      32B/32B
 4f4fb700ef54 Verifying Checksum
 4f4fb700ef54 Download complete
 e6f15f52e943 Verifying Checksum
 e6f15f52e943 Download complete
 8d33c6a288b6 Pull complete
 9f65a51c3904 Extracting [=>                                                 ]  32.77kB/1.003MB
 9f65a51c3904 Extracting [==================================================>]  1.003MB/1.003MB
 9f65a51c3904 Extracting [==================================================>]  1.003MB/1.003MB
 9f65a51c3904 Pull complete
 e6f15f52e943 Extracting [>                                                  ]  163.8kB/14.7MB
 98049c578bdc Downloading [==================================================>]     575B/575B
 98049c578bdc Verifying Checksum
 98049c578bdc Download complete
 e6f15f52e943 Extracting [==============================>                    ]  8.847MB/14.7MB
 e6f15f52e943 Extracting [==================================================>]   14.7MB/14.7MB
 e6f15f52e943 Pull complete
 ba6b3bb28d19 Extracting [==================================================>]      99B/99B
 ba6b3bb28d19 Extracting [==================================================>]      99B/99B
 ba6b3bb28d19 Pull complete
 4f4fb700ef54 Extracting [==================================================>]      32B/32B
 4f4fb700ef54 Extracting [==================================================>]      32B/32B
 4f4fb700ef54 Pull complete
 98049c578bdc Extracting [==================================================>]     575B/575B
 98049c578bdc Extracting [==================================================>]     575B/575B
 98049c578bdc Pull complete
 redis Pulled
 Network docker-compose-demo_default  Creating
 Network docker-compose-demo_default  Created
 Volume docker-compose-demo_redis-data  Creating
 Volume docker-compose-demo_redis-data  Created
 Container niteshift-redis  Creating
 Container niteshift-redis  Created
Error response from daemon: failed to set up container networking: failed to add interface vethe7db035 to sandbox: failed to subscribe to link updates: permission denied
