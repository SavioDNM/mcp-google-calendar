/**
 * Importa as bibliotecas necessárias.
 */
import * as functions from "firebase-functions";
import * as admin from "firebase-admin";
import axios from "axios";

// Inicializa o Firebase Admin SDK para que as funções possam interagir com outros serviços do Firebase.
admin.initializeApp();

/**
 * Define e exporta a Cloud Function `sendWhatsapp`.
 * Esta função é acionada por uma requisição HTTP POST.
 */
export const sendWhatsapp = functions.https.onRequest(async (request, response) => {
  // Verifica se o método da requisição é POST. Se não for, retorna um erro.
  if (request.method !== "POST") {
    response.status(405).send("Method Not Allowed");
    return;
  }

  // Extrai o número de destino (`to`) e a mensagem (`message`) do corpo da requisição.
  const { to, message } = request.body;

  // Valida se os dados necessários foram recebidos.
  if (!to || !message) {
    functions.logger.error("Requisição inválida: 'to' ou 'message' não foram fornecidos.", request.body);
    response.status(400).send("Bad Request: Faltando 'to' ou 'message' no corpo da requisição.");
    return;
  }

  // --- CONFIGURAÇÃO DA API DO WHATSAPP ---
  // ATENÇÃO: Armazene estes valores como segredos no seu projeto Firebase/Google Cloud.
  // NUNCA os coloque diretamente no código.
  const WHATSAPP_API_TOKEN = process.env.WHATSAPP_API_TOKEN; // Ex: functions.config().whatsapp.token
  const WHATSAPP_PHONE_NUMBER_ID = process.env.WHATSAPP_PHONE_NUMBER_ID; // Ex: functions.config().whatsapp.phone_id

  // Verifica se as variáveis de ambiente foram carregadas.
  if (!WHATSAPP_API_TOKEN || !WHATSAPP_PHONE_NUMBER_ID) {
    functions.logger.error("Segredos da API do WhatsApp não configurados nas variáveis de ambiente.");
    response.status(500).send("Internal Server Error: Configuração do servidor incompleta.");
    return;
  }

  // Monta a URL para a API de mensagens do WhatsApp Cloud.
  const url = `https://graph.facebook.com/v18.0/${WHATSAPP_PHONE_NUMBER_ID}/messages`;

  // Monta o corpo (payload) da requisição para a API do WhatsApp.
  const payload = {
    messaging_product: "whatsapp",
    to: to,
    type: "text",
    text: {
      body: message,
    },
  };

  // Define os headers da requisição, incluindo o token de autorização.
  const headers = {
    "Authorization": `Bearer ${WHATSAPP_API_TOKEN}`,
    "Content-Type": "application/json",
  };

  try {
    // Usa o Axios para fazer a chamada POST para a API do WhatsApp.
    functions.logger.info(`Enviando mensagem para ${to}`, { payload });
    await axios.post(url, payload, { headers });
    functions.logger.info("Mensagem enviada com sucesso pela API do WhatsApp.");
    
    // Retorna uma resposta de sucesso para o cliente (nosso app Python).
    response.status(200).send({ success: true, message: "Notificação enviada." });

  } catch (error: any) {
    // Em caso de erro, loga os detalhes e retorna uma resposta de erro.
    functions.logger.error("Erro ao enviar mensagem pela API do WhatsApp:", error.response?.data || error.message);
    response.status(500).send({ success: false, error: "Falha ao enviar a notificação." });
  }
});
