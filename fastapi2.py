from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from kubernetes import client, config
import boto3

app = FastAPI()

class K8sDeployRequest(BaseModel):
    kubeconfig: str
    cluster_name: str
    region: str
    container_image: str
    port: int

class EcsDeployRequest(BaseModel):
    aws_access_key_id: str
    aws_secret_access_key: str
    cluster_name: str
    container_image: str
    port: int

@app.post("/k8s-deploy")
def k8s_deploy(request: K8sDeployRequest):
    try:
        config.load_kube_config(config_file=request.kubeconfig)
        v1 = client.CoreV1Api()
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=request.cluster_name),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector={'matchLabels': {'app': request.cluster_name}},
                template=client.V1PodTemplateSpec(
                    metadata={'labels': {'app': request.cluster_name}},
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name=request.cluster_name,
                                image=request.container_image,
                                ports=[client.V1ContainerPort(container_port=request.port)],
                            )
                        ]
                    ),
                ),
            ),
        )
        apps_v1 = client.AppsV1Api()
        apps_v1.create_namespaced_deployment(namespace='default', body=deployment)
        return {"message": "Deployment successful"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/ecs-deploy")
def ecs_deploy(request: EcsDeployRequest):
    try:
        client = boto3.client(
            'ecs',
            aws_access_key_id=request.aws_access_key_id,
            aws_secret_access_key=request.aws_secret_access_key,
            region_name=request.region
        )
        response = client.run_task(
            cluster=request.cluster_name,
            taskDefinition=request.container_image,
            launchType='FARGATE',
            overrides={
                'containerOverrides': [
                    {
                        'name': request.cluster_name,
                        'image': request.container_image,
                        'portMappings': [
                            {
                                'containerPort': request.port,
                                'hostPort': request.port,
                                'protocol': 'tcp'
                            }
                        ]
                    }
                ]
            },
        )
        return {"message": "Deployment successful", "response": response}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))