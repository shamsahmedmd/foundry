using 'main.bicep'

param environmentName = 'dev'
param namePrefix = 'contoso'
param location = 'eastus2'
param modelDeploymentName = 'gpt-4.1-mini'
param modelCapacity = 30
param tags = {
  owner: 'ai-platform-team'
}
