package com.doublechaintech.onlinebookstoreservice;

import org.slf4j.MDC;
import io.teaql.runtime.DefaultUserContext;

public class CustomUserContext extends DefaultUserContext implements OnlineBookstoreServiceUserContext {
  public CustomUserContext(io.teaql.runtime.TeaQLRuntime runtime) {
    super(runtime);
  }
  public static final String USER_CONTEXT = "User-Context";
  public static final String ID_SPACE = "ID_SPACE";
  public static final String MERCHANT = "merchant";
  public static final String JOB = "job";

  public void init(Object request) {
    // String idSpace = getIdSpace();
    // if (idSpace != null) {
    //   MDC.put(ID_SPACE, idSpace);
    // }
  }

  public String getIdSpace() {
    return null; // getHeader(ID_SPACE);
  }
}